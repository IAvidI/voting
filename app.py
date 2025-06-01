# app.py
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import qrcode
import io
import base64
import uuid
import threading # For the timer

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key!'
socketio = SocketIO(app)

active_sessions = {} # session_id: {..., timer_object: None, timer_duration: 0, ...}

def generate_qr_code(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

@app.route('/')
def admin_index():
    return render_template('main_display.html')

@app.route('/join/<session_id>')
def resident_join_page(session_id):
    if session_id in active_sessions:
        session['current_session_id'] = session_id
        return render_template('resident_vote.html', session_id=session_id)
    return "Session not found or inactive.", 404

def server_tally_votes(session_id):
    with app.app_context(): # Needed for socketio calls from thread
        print(f"Server_tally_votes called for session {session_id} by timer/internal logic")
        if session_id in active_sessions and active_sessions[session_id]['status'] == 'voting':
            current_session = active_sessions[session_id]
            
            # Emit an event to main display that voting period is over (due to timer/all votes)
            # This can help the main display clear its own client-side timer if it was running one.
            socketio.emit('voting_ended_by_server', {'session_id': session_id}, room=session_id)

            # Proceed with tallying
            current_session['status'] = 'tallied'
            if current_session.get('timer_object'):
                current_session['timer_object'].cancel() # Ensure timer is cancelled
                current_session['timer_object'] = None

            # Calculate 'no_response' votes
            responded_sids = set(current_session['votes'].keys())
            all_resident_sids = set(current_session['residents'].keys())
            no_response_sids = all_resident_sids - responded_sids
            current_session['vote_counts']['no_response'] = len(no_response_sids)

            if current_session['vote_counts']['allow'] >= current_session['t']:
                current_session['outcome'] = 'Access Granted'
            else:
                current_session['outcome'] = 'Access Denied'

            print(f"Session {session_id}: Votes tallied. Outcome: {current_session['outcome']}")
            socketio.emit('votes_tallied', {
                'vote_counts': current_session['vote_counts'],
                'outcome': current_session['outcome'],
                'n': current_session['n'],
                't': current_session['t']
            }, room=session_id)
            # Notify residents voting has ended and the outcome
            socketio.emit('voting_ended', {'outcome': current_session['outcome']}, room=session_id, include_self=True)
        else:
            print(f"Attempted to tally for {session_id}, but not in voting status or session DNE.")


# --- SocketIO Events for Admin/Main Display ---
@socketio.on('create_session')
def handle_create_session():
    session_id = str(uuid.uuid4())[:8]
    active_sessions[session_id] = {
        'admin_sid': request.sid,
        'residents': {},
        'votes': {},
        'visitor_purpose': '',
        'extracted_info': '',
        'n': 0,
        't': 0,
        'status': 'pending', # 'pending', 'joining', 'voting', 'tallied'
        'vote_counts': {'allow': 0, 'deny': 0, 'abstain': 0, 'no_response': 0},
        'outcome': '',
        'timer_object': None,
        'timer_duration': 0
    }
    join_room(session_id)
    base_url = request.host_url 
    if not base_url.endswith('/'):
        base_url += '/'
    join_url = base_url + 'join/' + session_id
    qr_img_b64 = generate_qr_code(join_url)
    emit('session_created', {'session_id': session_id, 'qr_code': qr_img_b64, 'join_url': join_url})
    active_sessions[session_id]['status'] = 'joining' # Now open for joining
    print(f"Session {session_id} created by {request.sid}. Status: joining. Join URL: {join_url}")

@socketio.on('start_voting_round')
def handle_start_voting_round(data):
    session_id = data.get('session_id')
    purpose = data.get('visitor_purpose', 'N/A')
    timer_duration = data.get('timer_duration', 30) # Default 30s

    if session_id in active_sessions and active_sessions[session_id]['admin_sid'] == request.sid:
        current_session = active_sessions[session_id]
        
        # Cancel any existing timer for this session (e.g., if admin restarts a round quickly)
        if current_session.get('timer_object'):
            current_session['timer_object'].cancel()
            current_session['timer_object'] = None

        current_session['visitor_purpose'] = purpose
        current_session['extracted_info'] = f"Purpose: {purpose} (Info by NLP - sim.)"
        current_session['status'] = 'voting'
        current_session['n'] = len(current_session['residents'])
        current_session['t'] = (current_session['n'] // 2) + 1 if current_session['n'] > 0 else 1
        current_session['votes'] = {} 
        current_session['vote_counts'] = {'allow': 0, 'deny': 0, 'abstain': 0, 'no_response': current_session['n']}
        current_session['outcome'] = '' # Reset outcome
        current_session['timer_duration'] = timer_duration

        emit('voting_parameters_set', {
            'n': current_session['n'],
            't': current_session['t'],
            'visitor_purpose': current_session['visitor_purpose'],
            'extracted_info': current_session['extracted_info'],
            'timer_duration': timer_duration
        }, room=session_id)

        socketio.emit('voting_started', {
            'visitor_purpose': current_session['visitor_purpose'],
            'extracted_info': current_session['extracted_info'],
            'timer_duration': timer_duration
        }, room=session_id, include_self=False)

        # Start the server-side timer
        current_session['timer_object'] = threading.Timer(timer_duration, server_tally_votes, args=[session_id])
        current_session['timer_object'].start()

        print(f"Session {session_id}: Voting started. Purpose: {purpose}. n={current_session['n']}, t={current_session['t']}. Timer: {timer_duration}s.")
    else:
        emit('error', {'message': 'Session not found or you are not the admin.'})


@socketio.on('tally_votes') 
def handle_tally_votes_request(data): # Renamed to avoid conflict, this is for admin manual tally
    session_id = data.get('session_id')
    triggered_by_admin = data.get('triggered_by_admin', False)
    if session_id in active_sessions and active_sessions[session_id]['admin_sid'] == request.sid and triggered_by_admin:
        print(f"Admin manually requested tally for session {session_id}")
        if active_sessions[session_id]['status'] == 'voting':
            if active_sessions[session_id].get('timer_object'):
                active_sessions[session_id]['timer_object'].cancel() # Cancel existing timer
                active_sessions[session_id]['timer_object'] = None
            server_tally_votes(session_id) # Call the actual tally logic
        else:
            emit('error', {'message': 'Not in voting state to tally.'})
    elif not triggered_by_admin:
        # This event might be vestigial if server_tally_votes handles all logic
        pass


# --- SocketIO Events for Residents ---
@socketio.on('join_session_resident')
def handle_join_session_resident(data):
    session_id = data.get('session_id')
    nickname = data.get('nickname', f'Resident_{str(uuid.uuid4())[:4]}')

    if session_id in active_sessions:
        current_session = active_sessions[session_id]
        # Allow joining if session is 'pending', 'joining', or 'tallied' (i.e., not actively 'voting')
        if current_session['status'] != 'voting':
            if request.sid not in current_session['residents']: # Prevent re-joining if already in
                join_room(session_id) 
                current_session['residents'][request.sid] = nickname
                
                # If joining after a round, n for the next round will update when it starts.
                # For display purposes, update resident count to admin.
                emit('resident_joined_notification', {
                    'sid': request.sid, 
                    'nickname': nickname, 
                    'resident_count': len(current_session['residents'])
                }, room=current_session['admin_sid']) 
                
                emit('joined_successfully', {'nickname': nickname, 'session_id': session_id})
                print(f"Resident {nickname} ({request.sid}) joined session {session_id}. Current session status: {current_session['status']}. Total residents: {len(current_session['residents'])}")
            else:
                 emit('joined_successfully', {'nickname': current_session['residents'][request.sid], 'session_id': session_id, 'message': 'Reconnected or already joined.'})
        else:
            emit('error', {'message': 'Voting is currently in progress. Please try again later.'})
    else:
        emit('error', {'message': 'Session ID not found.'})

@socketio.on('submit_vote')
def handle_submit_vote(data):
    session_id = data.get('session_id')
    vote_type = data.get('vote_type') 

    if session_id in active_sessions:
        current_session = active_sessions[session_id]
        if current_session['status'] == 'voting' and request.sid in current_session['residents']:
            if request.sid not in current_session['votes']: 
                current_session['votes'][request.sid] = vote_type
                current_session['vote_counts'][vote_type] += 1
                current_session['vote_counts']['no_response'] -=1


                emit('vote_update', { 
                    'sid': request.sid,
                    'vote_counts': current_session['vote_counts'],
                    'votes_received_count': len(current_session['votes'])
                }, room=current_session['admin_sid'])
                emit('vote_submitted_confirmation', {'status': 'Vote recorded'})
                print(f"Session {session_id}: Vote '{vote_type}' from {current_session['residents'][request.sid]} ({request.sid})")

                # Check if all residents have voted
                if len(current_session['votes']) == current_session['n'] and current_session['n'] > 0:
                    print(f"All {current_session['n']} votes received for session {session_id}. Triggering early tally.")
                    if current_session.get('timer_object'):
                        current_session['timer_object'].cancel()
                        current_session['timer_object'] = None
                    server_tally_votes(session_id)
                    # socketio.start_background_task(server_tally_votes, session_id)
            else:
                emit('error', {'message': 'You have already voted.'})
        else:
            emit('error', {'message': 'Voting is not active or you are not a resident.'})
    else:
        emit('error', {'message': 'Session ID not found.'})


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    for session_id, details in list(active_sessions.items()): # Iterate over a copy
        if request.sid == details.get('admin_sid'):
            print(f"Admin for session {session_id} disconnected. Cleaning up session.")
            if details.get('timer_object'):
                details['timer_object'].cancel()
            socketio.emit('error', {'message': 'Admin disconnected. Session terminated.'}, room=session_id)
            # socketio.close_room(session_id) # This might cause issues if other events are pending
            if session_id in active_sessions: # Check if not already deleted by another op
                del active_sessions[session_id]
            break
        if request.sid in details.get('residents', {}):
            nickname = details['residents'].pop(request.sid)
            
            # If resident disconnects during voting and hasn't voted
            if details['status'] == 'voting' and request.sid not in details.get('votes', {}):
                details['vote_counts']['no_response'] -= 1 # They won't be a 'no response' anymore if they left
                # The number of expected votes 'n' effectively decreases for this round if we don't re-calc 't'
                # Or, we can let them be a 'no response' and n/t remain static for the round
                # For simplicity, let 'n' and 't' for the current round remain. Tally will count them as non-voter.
                # If they had voted, their vote is still counted. The 'pop' below handles if we want to remove their vote.

            # If we want to remove vote of disconnected user (more complex, 't' might need re-eval)
            # if request.sid in details.get('votes', {}):
            #     vote_type = details['votes'].pop(request.sid)
            #     details['vote_counts'][vote_type] -= 1
            
            # Notify admin about the disconnected resident
            # The count for 'n' for current round should ideally remain fixed once voting starts.
            # For display, the admin will see one less *active* resident.
            emit('resident_left_notification', {
                'sid': request.sid,
                'nickname': nickname,
                'resident_count': len(details['residents']), # Current number of connected residents
                'vote_counts': details['vote_counts'], 
                'votes_received_count': len(details['votes'])
            }, room=details.get('admin_sid'))
            print(f"Resident {nickname} ({request.sid}) disconnected from session {session_id}. Remaining connected: {len(details['residents'])}")
            
            # If voting was active and this was the last vote needed (or all remaining have voted)
            # and they were the last one, this could trigger an early tally.
            current_n_for_round = details.get('n', 0) # 'n' at the start of the round
            if details['status'] == 'voting' and len(details['votes']) == current_n_for_round and current_n_for_round > 0:
                 if details.get('timer_object'):
                    details['timer_object'].cancel()
                    details['timer_object'] = None
                 server_tally_votes(session_id)
            break


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)