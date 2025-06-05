def calculate_dynamic_voting_parameters(structured_nlp_output, num_voters):
    """
    Calculates dynamic voting threshold 't' and reason based on NLP output and number of voters.
    """
    policy_reason = "Default policy: Simple majority"
    
    # Base threshold (e.g., simple majority)
    if num_voters == 0:
        t_threshold = 0 # No one to vote
    elif num_voters == 1:
        t_threshold = 1 # Single voter decides
    else:
        t_threshold = (num_voters // 2) + 1

    nlp_intent = structured_nlp_output.get('intent', 'inquiry')
    nlp_category = structured_nlp_output.get('visitor_category', 'unknown_visitor')

    if nlp_intent == 'delivery_request' and 'courier' in nlp_category:
        if num_voters >= 1:
            t_threshold = 1 # Trusted courier, low threshold
            policy_reason = f"Policy: Recognized courier ({nlp_category}), low threshold."
        else:
            t_threshold = 0 # No voters, auto-allow for PoC (or could be auto-deny)
            policy_reason = "Policy: Recognized courier, no voters available (auto-decision)."
    
    elif nlp_intent == 'guest_access_request' and nlp_category in ['guest_general', 'unknown_visitor']:
        if num_voters >= 2:
            # Increase threshold slightly for unknown guests, but not more than num_voters
            t_threshold = min(num_voters, ((num_voters // 2) + 1) + 1 if num_voters > 1 else 1)
            policy_reason = "Policy: General/Unknown guest, slightly increased threshold."
        # else (1 voter), default majority (which is 1) is fine
    
    elif nlp_intent == 'service_request' and 'technician' in nlp_category:
        if num_voters >= 1:
            t_threshold = 1 # Assume scheduled/verified service personnel
            policy_reason = f"Policy: Assumed verified service personnel ({nlp_category}), low threshold."
        else:
            t_threshold = 0
            policy_reason = "Policy: Service personnel, no voters available (auto-decision)."

    elif nlp_intent == 'emergency_access' or nlp_intent == 'emergency_alert':
        t_threshold = 1 if num_voters > 0 else 0 # Minimal threshold for emergency
        policy_reason = "Policy: Emergency indicated, minimal threshold."

    # Ensure t_threshold is valid
    if num_voters > 0:
        t_threshold = max(1, min(t_threshold, num_voters))
    elif num_voters == 0: # Explicitly handle no voters
        t_threshold = 0 


    print(f"Policy Module: Intent='{nlp_intent}', Category='{nlp_category}', Voters={num_voters} -> t={t_threshold}, Reason='{policy_reason}'")
    return {'t_threshold': t_threshold, 'policy_reason': policy_reason}
