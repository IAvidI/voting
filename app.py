from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import qrcode
import io
import base64
import uuid
import threading # For the timer

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key!' # Replace with a real secret key
socketio = SocketIO(app)

active_sessions = {}

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
    # Ensure session_id is in active_sessions BEFORE rendering
    if session_id in active_sessions:
        # session['current_session_id'] = session_id # Client gets session_id via URL param, this server-side session var is not strictly needed for client
        return render_template('resident_vote.html', session_id=session_id)
    return "Session not found or inactive.", 404

def server_tally_votes(session_id):
    with app.app_context():
        print(f"Server_tally_votes called for session {session_id}")
        if session_id in active_sessions and active_sessions[session_id]['status'] == 'voting':
            current_session = active_sessions[session_id]

            # Cancel the timer if it's still active
            if current_session.get('timer_object'):
                current_session['timer_object'].cancel()
                current_session['timer_object'] = None
            
            current_session['status'] = 'tallied'
            print(f"Session {session_id} status changed to 'tallied'")

            # Calculate 'no_response' votes based on 'residents_voting' and actual votes received
            responded_sids = set(current_session['votes'].keys())
            # Voters are those in residents_voting at the START of the voting round.
            # n_voters was set when voting started.
            expected_voter_sids = set(current_session['residents_voting'].keys()) # These are the SIDs of those who *should* have voted
            
            # This calculation of no_response was faulty in previous user version.
            # Correct approach: no_response_count = n_voters_at_start_of_round - number_of_votes_actually_cast
            # The current_session['vote_counts']['no_response'] is decremented upon vote.
            # If timer expires, those who haven't voted remain in 'no_response' count.
            # Let's ensure vote_counts['no_response'] is correct.
            # It's initialized to n_voters and decremented per vote. So it should be fine.

            if current_session['vote_counts']['allow'] >= current_session['t_threshold']: # Use t_threshold
                current_session['outcome'] = 'Access Granted'
            else:
                current_session['outcome'] = 'Access Denied'

            print(f"Session {session_id}: Votes tallied. Outcome: {current_session['outcome']}")
            
            # Notify admin display
            socketio.emit('votes_tallied', {
                'vote_counts': current_session['vote_counts'],
                'outcome': current_session['outcome'],
                'n': current_session['n_voters'], # Use n_voters
                't': current_session['t_threshold'] # Use t_threshold
            }, room=current_session['admin_sid']) # Target admin specifically

            # Notify residents (voters)
            for resident_sid in current_session['residents_voting'].keys():
                socketio.emit('voting_ended', {
                    'outcome': current_session['outcome']
                }, room=resident_sid)
            
            # Notify the visitor
            if current_session.get('visitor_sid'):
                socketio.emit('visitor_outcome', {
                    'outcome': current_session['outcome'],
                    # 'message': f"Outcome: {current_session['outcome']}."
                }, room=current_session['visitor_sid'])
            
            # General 'voting_ended_by_server' is good for admin log, but results are above
            socketio.emit('voting_ended_by_server', {'session_id': session_id, 'reason': 'Tally complete'}, room=current_session['admin_sid'])

        elif session_id in active_sessions and active_sessions[session_id]['status'] == 'tallied':
             print(f"Session {session_id} already tallied. Ignoring redundant tally call.")
        else:
            print(f"Attempted to tally for {session_id}, but session not found or not in 'voting' status. Current status: {active_sessions.get(session_id, {}).get('status')}")


@socketio.on('create_session')
def handle_create_session():
    session_id = str(uuid.uuid4())[:8]
    active_sessions[session_id] = {
        'admin_sid': request.sid,
        'all_connected_users': {},
        'residents_voting': {}, 
        'visitor_sid': None,
        'visitor_nickname': None,
        'votes': {},
        'visitor_purpose': '',
        'extracted_info': '',
        'n_voters': 0,
        't_threshold': 0,
        'status': 'role_assignment', # Start with role assignment
        'vote_counts': {'allow': 0, 'deny': 0, 'abstain': 0, 'no_response': 0},
        'outcome': '',
        'timer_object': None,
        'timer_duration': 0
    }
    join_room(session_id) # Admin joins the session room
    base_url = request.host_url 
    if not base_url.endswith('/'):
        base_url += '/'
    join_url = base_url + 'join/' + session_id
    qr_img_b64 = generate_qr_code(join_url)
    # Emit only to the creator (admin)
    emit('session_created', {'session_id': session_id, 'qr_code': qr_img_b64, 'join_url': join_url})
    print(f"Session {session_id} created by admin {request.sid}. Status: role_assignment.")

@socketio.on('admin_assign_visitor_role')
def handle_admin_assign_visitor_role(data):
    session_id = data.get('session_id')
    visitor_candidate_sid = data.get('visitor_sid')

    if session_id in active_sessions and active_sessions[session_id]['admin_sid'] == request.sid:
        current_session = active_sessions[session_id]
        
        # If a visitor already exists and is different from the new candidate
        if current_session['visitor_sid'] and current_session['visitor_sid'] != visitor_candidate_sid:
            old_visitor_sid = current_session['visitor_sid']
            if old_visitor_sid in current_session['all_connected_users']:
                 current_session['all_connected_users'][old_visitor_sid]['role'] = 'resident'
                 socketio.emit('role_assigned', {
                     'your_role': 'resident', 
                     'visitor_nickname': None # New visitor will be set shortly
                    }, room=old_visitor_sid)

        # Assign new visitor
        if visitor_candidate_sid in current_session['all_connected_users']:
            current_session['visitor_sid'] = visitor_candidate_sid
            current_session['visitor_nickname'] = current_session['all_connected_users'][visitor_candidate_sid]['nickname']
            current_session['all_connected_users'][visitor_candidate_sid]['role'] = 'visitor'
            current_session['status'] = 'waiting_for_purpose'

            current_session['residents_voting'] = {}
            for sid, user_data in current_session['all_connected_users'].items():
                if sid != current_session['admin_sid'] and sid != current_session['visitor_sid']:
                    current_session['all_connected_users'][sid]['role'] = 'resident'
                    current_session['residents_voting'][sid] = user_data['nickname']
                    socketio.emit('role_assigned', {
                        'your_role': 'resident', 
                        'visitor_nickname': current_session['visitor_nickname']
                        }, room=sid)
                elif sid == current_session['visitor_sid']:
                     socketio.emit('role_assigned', {
                        'your_role': 'visitor', 
                        'visitor_nickname': current_session['visitor_nickname']
                        }, room=sid)
            
            emit('visitor_role_confirmed', { # To Admin
                'visitor_sid': current_session['visitor_sid'],
                'visitor_nickname': current_session['visitor_nickname'],
                'residents_for_voting_count': len(current_session['residents_voting'])
            }, room=current_session['admin_sid'])
            print(f"Session {session_id}: {current_session['visitor_nickname']} assigned as Visitor.")
        else:
            emit('error', {'message': 'Selected user for visitor role not found.'})
    else:
        emit('error', {'message': 'Admin/Session error during role assignment.'})


@socketio.on('visitor_submit_purpose')
def handle_visitor_submit_purpose(data):
    session_id = data.get('session_id')
    purpose_text = data.get('purpose')

    if session_id in active_sessions:
        current_session = active_sessions[session_id]
        if request.sid == current_session.get('visitor_sid') and current_session['status'] == 'waiting_for_purpose':
            current_session['visitor_purpose'] = purpose_text
            # current_session['extracted_info'] = f"Purpose: {purpose_text} (Visitor: {current_session['visitor_nickname']})" # Simple extraction
            current_session['extracted_info'] = purpose_text # Simple extraction
            current_session['status'] = 'ready_for_voting'

            emit('purpose_received_from_visitor', { # To Admin
                'visitor_nickname': current_session['visitor_nickname'],
                'purpose': purpose_text,
                'extracted_info': current_session['extracted_info']
            }, room=current_session['admin_sid'])
            emit('purpose_submission_confirmed', {'status': 'Purpose submitted, awaiting voting.'}, room=request.sid) # To Visitor
            print(f"Session {session_id}: Purpose '{purpose_text}' received from visitor.")
        else:
            emit('error', {'message': 'Not authorized or session not in correct state for purpose submission.'})

@socketio.on('start_voting_round')
def handle_start_voting_round(data):
    session_id = data.get('session_id')
    timer_duration = data.get('timer_duration', 30)

    if session_id in active_sessions and active_sessions[session_id]['admin_sid'] == request.sid:
        current_session = active_sessions[session_id]

        if not current_session.get('visitor_sid') or not current_session.get('visitor_purpose'):
            emit('error', {'message': 'Visitor not assigned or purpose not stated.'})
            return
        
        if current_session['status'] not in ['ready_for_voting', 'tallied']:
            emit('error', {'message': f"Cannot start voting. Current status: {current_session['status']}"})
            return

        if current_session.get('timer_object'): # Clear previous timer
            current_session['timer_object'].cancel()
        
        current_session['status'] = 'voting'
        current_session['n_voters'] = len(current_session['residents_voting'])
        current_session['t_threshold'] = (current_session['n_voters'] // 2) + 1 if current_session['n_voters'] > 0 else 1
        current_session['votes'] = {} 
        current_session['vote_counts'] = {'allow': 0, 'deny': 0, 'abstain': 0, 'no_response': current_session['n_voters']}
        current_session['outcome'] = '' # Reset outcome
        current_session['timer_duration'] = timer_duration
        
        # This data is sent to Admin display
        emit('voting_parameters_set', {
            'n': current_session['n_voters'], # CONSISTENTLY USE 'n' and 't' for this event if main_display expects it
            't': current_session['t_threshold'],# OR change main_display to expect n_voters, t_threshold
            'visitor_purpose': current_session['visitor_purpose'],
            'extracted_info': current_session['extracted_info'],
            'timer_duration': timer_duration,
            'visitor_nickname': current_session['visitor_nickname']
        }, room=current_session['admin_sid']) # Send only to admin

        # Notify residents (actual voters) to start voting
        for resident_sid in current_session['residents_voting'].keys():
            socketio.emit('voting_started', {
                'visitor_nickname': current_session['visitor_nickname'],
                'visitor_purpose': current_session['visitor_purpose'],
                'extracted_info': current_session['extracted_info'],
                'timer_duration': timer_duration
            }, room=resident_sid)
        
        current_session['timer_object'] = threading.Timer(timer_duration, server_tally_votes, args=[session_id])
        current_session['timer_object'].start()
        print(f"Session {session_id}: Voting started. Voters: {current_session['n_voters']}, Threshold: {current_session['t_threshold']}.")
    else:
        emit('error', {'message': 'Admin/Session error or not ready for voting.'})

@socketio.on('tally_votes') 
def handle_tally_votes_request(data):
    session_id = data.get('session_id')
    if session_id in active_sessions and active_sessions[session_id]['admin_sid'] == request.sid:
        current_session = active_sessions[session_id]
        if current_session['status'] == 'voting':
            print(f"Admin manually requested tally for session {session_id}")
            if current_session.get('timer_object'):
                current_session['timer_object'].cancel()
                current_session['timer_object'] = None
            server_tally_votes(session_id)
        else:
            emit('error', {'message': 'Not in voting state to tally manually.'})

@socketio.on('admin_reset_round')
def handle_admin_reset_round(data):
    session_id = data.get('session_id')
    if session_id in active_sessions and active_sessions[session_id]['admin_sid'] == request.sid:
        current_session = active_sessions[session_id]

        print(f"Admin resetting round for session {session_id}")

        # Cancel any existing timer
        if current_session.get('timer_object'):
            current_session['timer_object'].cancel()
            current_session['timer_object'] = None

        # Reset session variables for a new round
        current_session['visitor_sid'] = None
        current_session['visitor_nickname'] = None
        current_session['visitor_purpose'] = ''
        current_session['extracted_info'] = ''
        current_session['votes'] = {}
        current_session['vote_counts'] = {'allow': 0, 'deny': 0, 'abstain': 0, 'no_response': 0}
        current_session['outcome'] = ''
        current_session['n_voters'] = 0
        current_session['t_threshold'] = 0
        current_session['status'] = 'role_assignment' # Back to role assignment phase

        # Reset roles for all connected users and notify them
        for sid, user_data in current_session['all_connected_users'].items():
            user_data['role'] = 'unassigned' # Reset their role
            socketio.emit('role_assigned', {
                'your_role': 'unassigned',
                'visitor_nickname': None # No visitor assigned yet
            }, room=sid)
        
        # Notify admin that reset is done and to re-render their user list for assignment
        emit('round_was_reset', {
            'all_users': current_session['all_connected_users'],
            'message': 'Round has been reset. Please assign roles.'
        }, room=current_session['admin_sid'])
        
        print(f"Session {session_id} reset to 'role_assignment'. All users set to 'unassigned'.")
    else:
        emit('error', {'message': 'Failed to reset round. Session/Admin mismatch.'})

# --- User Client Events ---
@socketio.on('join_session_resident') # Renamed from old file for clarity with roles
def handle_user_join(data): # Changed function name
    session_id = data.get('session_id')
    nickname = data.get('nickname', f'User_{str(uuid.uuid4())[:4]}').strip()

    if not nickname:
        emit('error', {'message': 'Nickname cannot be empty.'})
        return

    if session_id in active_sessions:
        current_session = active_sessions[session_id]

        if request.sid in current_session['all_connected_users']: # Already connected (e.g. refresh)
            user_data = current_session['all_connected_users'][request.sid]
            emit('joined_successfully_waiting_role', {'nickname': user_data['nickname'], 'session_id': session_id, 'message': 'Reconnected.'})
            socketio.emit('role_assigned', { # Resend current role
                'your_role': user_data['role'],
                'visitor_nickname': current_session.get('visitor_nickname')
            }, room=request.sid)
            return

        for user_data_val in current_session['all_connected_users'].values(): # Check by value
            if user_data_val['nickname'] == nickname:
                emit('nickname_taken_error', {'message': f"Nickname '{nickname}' is already taken."})
                return
        
        join_room(session_id) # User joins the general session room
        current_session['all_connected_users'][request.sid] = {'nickname': nickname, 'role': 'unassigned'}
        
        emit('user_joined_for_roles', { # To Admin
            'sid': request.sid,
            'nickname': nickname,
            'all_users': current_session['all_connected_users']
        }, room=current_session['admin_sid'])
        
        emit('joined_successfully_waiting_role', {'nickname': nickname, 'session_id': session_id}) # To joining client
        print(f"User {nickname} ({request.sid}) joined session {session_id}. Awaiting role.")
    else:
        emit('error', {'message': 'Session ID not found.'})


@socketio.on('submit_vote')
def handle_submit_vote(data):
    session_id = data.get('session_id')
    vote_type = data.get('vote_type') 

    if session_id in active_sessions:
        current_session = active_sessions[session_id]
        if current_session['status'] == 'voting' and request.sid in current_session['residents_voting']:
            if request.sid not in current_session['votes']: 
                current_session['votes'][request.sid] = vote_type
                current_session['vote_counts'][vote_type] += 1
                if current_session['vote_counts']['no_response'] > 0:
                     current_session['vote_counts']['no_response'] -=1
                
                resident_nickname = current_session['residents_voting'][request.sid]
                
                emit('vote_update', { 
                    'sid': request.sid, # For admin to know who voted, if needed
                    'vote_counts': current_session['vote_counts'],
                    'votes_received_count': len(current_session['votes'])
                }, room=current_session['admin_sid'])
                emit('vote_submitted_confirmation', {'status': 'Vote recorded'}) # To voter
                print(f"Session {session_id}: Vote '{vote_type}' from {resident_nickname} ({request.sid})")

                if len(current_session['votes']) == current_session['n_voters'] and current_session['n_voters'] > 0:
                    print(f"All {current_session['n_voters']} votes received. Triggering early tally.")
                    if current_session.get('timer_object'):
                        current_session['timer_object'].cancel()
                        current_session['timer_object'] = None
                    # Use background task as it was more reliable for the "last voter" issue
                    socketio.start_background_task(server_tally_votes, session_id)
            else:
                emit('error', {'message': 'You have already voted.'})
        else:
            emit('error', {'message': 'Voting is not active or you are not a designated voter.'})
    else:
        emit('error', {'message': 'Session ID not found.'})


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    for session_id, details in list(active_sessions.items()):
        if request.sid == details.get('admin_sid'):
            print(f"Admin for session {session_id} disconnected. Cleaning up session.")
            if details.get('timer_object'): details['timer_object'].cancel()
            # Notify all other users in the room before deleting session
            other_users_in_session = [sid for sid in details.get('all_connected_users', {}) if sid != request.sid]
            for user_sid in other_users_in_session:
                socketio.emit('error', {'message': 'Admin disconnected. Session terminated.'}, room=user_sid)
            
            if session_id in active_sessions: del active_sessions[session_id]
            break
        
        user_disconnected_data = details.get('all_connected_users', {}).pop(request.sid, None)
        if user_disconnected_data:
            nickname = user_disconnected_data['nickname']
            print(f"User {nickname} (SID: {request.sid}) disconnected from session {session_id}.")

            was_visitor = (request.sid == details.get('visitor_sid'))
            was_voting_resident = (request.sid in details.get('residents_voting', {}))

            if was_visitor:
                details['visitor_sid'] = None
                details['visitor_nickname'] = None
                details['visitor_purpose'] = ''
                details['status'] = 'role_assignment' # Reset to role assignment
                socketio.emit('visitor_left_role_reset', {
                    'message': f"Visitor {nickname} disconnected. Please assign a new visitor.",
                    'all_users': details['all_connected_users']
                }, room=details['admin_sid'])

            if was_voting_resident:
                details['residents_voting'].pop(request.sid, None)
                # If voting was active and this resident hadn't voted, their 'no_response' vote is implicitly handled by tally logic
                # If they had voted, their vote is still in 'details['votes']' unless explicitly removed.
                # Let's assume votes cast before disconnect are kept.
                # Tally logic uses n_voters from start of round, so 'no_response' naturally covers this.

            # Notify admin about the general user disconnection to update their list
            emit('user_left_for_roles', {
                'sid': request.sid, # SID of the user who left
                'nickname': nickname,
                'all_users': details['all_connected_users'] # Updated list
            }, room=details.get('admin_sid'))

            # Check if all *remaining* voters have voted if voting was active
            if details['status'] == 'voting' and details['n_voters'] > 0 and was_voting_resident:
                all_remaining_designated_voters_have_voted = True
                # Check if all SIDs in residents_voting (which now excludes the disconnected) are in votes
                if not details['residents_voting']: # No voters left (e.g. last voter disconnected)
                     # If there were votes cast before this, and no more voters are left
                    if len(details['votes']) > 0 or details['n_voters'] == len(details['votes']): # Or if expected votes met
                         all_remaining_designated_voters_have_voted = True
                    else: # No voters left and no votes cast (or not enough)
                        all_remaining_designated_voters_have_voted = False # or true depending on logic
                else:
                    for r_sid in details['residents_voting']:
                        if r_sid not in details['votes']:
                            all_remaining_designated_voters_have_voted = False
                            break
                
                # If all originally expected voters (n_voters) have submitted, OR
                # if the number of votes matches the *new* count of residents_voting (meaning those still connected have all voted)
                # This logic is tricky. The simplest is to rely on the original n_voters for the round.
                # A disconnect effectively means that person cannot vote.
                # The 'no_response' count logic in server_tally_votes will handle this.
                # However, if ALL originally designated voters have either voted OR disconnected,
                # and among those who did not disconnect, all have voted, then we can tally.
                
                # Simpler: if len(votes) == n_voters (original count for the round)
                # The 'n_voters' for the round is fixed. Disconnected users who didn't vote will be 'no_response'.
                # If the disconnection was the last action needed to account for all n_voters (either voted or disconnected)
                # Let server_tally_votes handle it on timer or when actual votes meet n_voters.
                # This check is mostly for if the *number of votes received* now matches the n_voters,
                # which wouldn't be changed by a disconnect unless the vote was also removed.
                if len(details['votes']) == details['n_voters']:
                    print(f"Disconnect: All {details['n_voters']} expected votes now accounted for in session {session_id}. Triggering early tally.")
                    if details.get('timer_object'): details['timer_object'].cancel()
                    socketio.start_background_task(server_tally_votes, session_id)
            break


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)