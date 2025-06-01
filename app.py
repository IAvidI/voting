# app.py
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import qrcode
import io
import base64
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key!' # Replace with a real secret key
socketio = SocketIO(app)

# In-memory storage for sessions and votes
# In a real app, you might use a database
active_sessions = {} # session_id: {admin_sid: '', residents: {sid: name}, votes: {}, visitor_purpose: '', n: 0, t: 0, status: 'pending'}

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
        # Store session_id for the resident, could also pass to template directly
        session['current_session_id'] = session_id
        return render_template('resident_vote.html', session_id=session_id)
    return "Session not found or inactive.", 404

# --- SocketIO Events for Admin/Main Display ---
@socketio.on('create_session')
def handle_create_session(): # Removed 'data' parameter
    session_id = str(uuid.uuid4())[:8] # Short unique ID
    active_sessions[session_id] = {
        'admin_sid': request.sid,
        'residents': {}, # sid: nickname (optional)
        'votes': {}, # sid: vote_type ('allow', 'deny', 'abstain')
        'visitor_purpose': '',
        'extracted_info': '',
        'n': 0,
        't': 0,
        'status': 'joining', # joining, voting, tallied
        'vote_counts': {'allow': 0, 'deny': 0, 'abstain': 0, 'no_response': 0},
        'outcome': ''
    }
    join_room(session_id) # Admin joins the room
    # Construct the base URL more reliably
    base_url = request.host_url.replace('http://', 'http://') # ensure it's http for local, adjust if https needed
    if not base_url.endswith('/'):
        base_url += '/'
    join_url = base_url + 'join/' + session_id

    qr_img_b64 = generate_qr_code(join_url)
    emit('session_created', {'session_id': session_id, 'qr_code': qr_img_b64, 'join_url': join_url})
    print(f"Session {session_id} created by {request.sid}. Join URL: {join_url}")

@socketio.on('start_voting_round')
def handle_start_voting_round(data):
    session_id = data.get('session_id')
    purpose = data.get('visitor_purpose', 'N/A')
    if session_id in active_sessions and active_sessions[session_id]['admin_sid'] == request.sid:
        current_session = active_sessions[session_id]
        current_session['visitor_purpose'] = purpose
        # Simulate NLP extraction
        current_session['extracted_info'] = f"Purpose: {purpose} (Info extracted by NLP - simulated)"
        current_session['status'] = 'voting'
        current_session['n'] = len(current_session['residents'])
        current_session['t'] = (current_session['n'] // 2) + 1 if current_session['n'] > 0 else 1
        current_session['votes'] = {} # Reset votes for the new round
        current_session['vote_counts'] = {'allow': 0, 'deny': 0, 'abstain': 0, 'no_response': current_session['n']}


        # Notify main display about voting parameters
        emit('voting_parameters_set', {
            'n': current_session['n'],
            't': current_session['t'],
            'visitor_purpose': current_session['visitor_purpose'],
            'extracted_info': current_session['extracted_info']
        }, room=session_id)

        # Notify residents to start voting
        socketio.emit('voting_started', {
            'visitor_purpose': current_session['visitor_purpose'],
            'extracted_info': current_session['extracted_info']
        }, room=session_id, include_self=False) # Don't send to admin

        print(f"Session {session_id}: Voting started by admin. Purpose: {purpose}. n={current_session['n']}, t={current_session['t']}")
        # TODO: Add voting timer logic here
    else:
        emit('error', {'message': 'Session not found or you are not the admin.'})


@socketio.on('tally_votes') # Can be triggered by admin or by timer
def handle_tally_votes(data):
    session_id = data.get('session_id')
    if session_id in active_sessions and active_sessions[session_id]['status'] == 'voting':
        current_session = active_sessions[session_id]
        current_session['status'] = 'tallied'

        # Calculate 'no_response' votes
        responded_sids = set(current_session['votes'].keys())
        all_resident_sids = set(current_session['residents'].keys())
        no_response_sids = all_resident_sids - responded_sids
        current_session['vote_counts']['no_response'] = len(no_response_sids)


        # Determine outcome
        if current_session['vote_counts']['allow'] >= current_session['t']:
            current_session['outcome'] = 'Access Granted'
        else:
            current_session['outcome'] = 'Access Denied'

        print(f"Session {session_id}: Votes tallied. Outcome: {current_session['outcome']}")
        emit('votes_tallied', {
            'vote_counts': current_session['vote_counts'],
            'outcome': current_session['outcome'],
            'n': current_session['n'],
            't': current_session['t']
        }, room=session_id)
        socketio.emit('voting_ended', {'outcome': current_session['outcome']}, room=session_id, include_self=False)


# --- SocketIO Events for Residents ---
@socketio.on('join_session_resident')
def handle_join_session_resident(data):
    session_id = data.get('session_id')
    nickname = data.get('nickname', f'Resident_{str(uuid.uuid4())[:4]}') # Optional: allow resident to set nickname

    if session_id in active_sessions:
        current_session = active_sessions[session_id]
        if current_session['status'] == 'joining' or current_session['status'] == 'pending': # Allow joining before voting starts
            join_room(session_id) # Resident joins the room
            current_session['residents'][request.sid] = nickname
            current_session['n'] = len(current_session['residents']) # Update n
            current_session['vote_counts']['no_response'] = current_session['n'] - len(current_session['votes'])


            emit('resident_joined_notification', {'sid': request.sid, 'nickname': nickname, 'resident_count': len(current_session['residents'])}, room=session_id) # Notify admin/main display
            emit('joined_successfully', {'nickname': nickname, 'session_id': session_id}) # Confirm to resident
            print(f"Resident {nickname} ({request.sid}) joined session {session_id}. Total residents: {len(current_session['residents'])}")
        else:
            emit('error', {'message': 'Voting has already started or ended for this session.'})
    else:
        emit('error', {'message': 'Session ID not found.'})

@socketio.on('submit_vote')
def handle_submit_vote(data):
    session_id = data.get('session_id')
    vote_type = data.get('vote_type') # 'allow', 'deny', 'abstain'

    if session_id in active_sessions:
        current_session = active_sessions[session_id]
        if current_session['status'] == 'voting' and request.sid in current_session['residents']:
            if request.sid not in current_session['votes']: # Allow voting only once
                current_session['votes'][request.sid] = vote_type
                current_session['vote_counts'][vote_type] += 1
                current_session['vote_counts']['no_response'] -=1


                emit('vote_update', { # Update main display in real-time
                    'sid': request.sid,
                    'vote_counts': current_session['vote_counts'],
                    'votes_received_count': len(current_session['votes'])
                }, room=current_session['admin_sid'])
                emit('vote_submitted_confirmation', {'status': 'Vote recorded'})
                print(f"Session {session_id}: Vote '{vote_type}' from {current_session['residents'][request.sid]} ({request.sid})")

                # Optional: Auto-tally if all votes are in
                # if len(current_session['votes']) == current_session['n']:
                #     handle_tally_votes({'session_id': session_id})
            else:
                emit('error', {'message': 'You have already voted.'})
        else:
            emit('error', {'message': 'Voting is not active or you are not part of this session\'s residents.'})
    else:
        emit('error', {'message': 'Session ID not found.'})


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    # Handle resident or admin disconnecting
    for session_id, details in list(active_sessions.items()):
        if request.sid == details['admin_sid']:
            print(f"Admin for session {session_id} disconnected. Cleaning up session.")
            socketio.emit('error', {'message': 'Admin disconnected. Session terminated.'}, room=session_id, include_self=False)
            socketio.close_room(session_id)
            del active_sessions[session_id]
            break
        if request.sid in details['residents']:
            nickname = details['residents'].pop(request.sid)
            details['n'] = len(details['residents'])
             # If voting was active and they hadn't voted, update no_response if needed
            if details['status'] == 'voting' and request.sid not in details['votes']:
                # This logic is tricky, as "no_response" is also calculated at tally. Simpler to let tally handle it.
                pass
            elif request.sid in details['votes']: # They had voted
                vote_type = details['votes'].pop(request.sid) # Remove their vote
                details['vote_counts'][vote_type] -= 1

            print(f"Resident {nickname} ({request.sid}) disconnected from session {session_id}. Remaining: {details['n']}")
            socketio.emit('resident_left_notification', {
                'sid': request.sid,
                'nickname': nickname,
                'resident_count': details['n'],
                'vote_counts': details['vote_counts'], # Send updated counts
                'votes_received_count': len(details['votes'])
            }, room=details['admin_sid'])
            # If session becomes empty of residents and was created, consider cleanup or marking as inactive
            # if not details['residents'] and details['status'] != 'pending':
            #     pass # Or clean up

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)