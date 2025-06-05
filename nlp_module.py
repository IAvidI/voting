import spacy        # For the NLP

# Load the spaCy model once when the app starts
try:
    nlp = spacy.load("en_core_web_sm")
    print("spaCy model 'en_core_web_sm' loaded successfully.")
except OSError:
    print("spaCy model 'en_core_web_sm' not found. Please run: python -m spacy download en_core_web_sm")
    nlp = None # Fallback or handle error appropriately

# --- NLP Processing Function ---
def process_visitor_purpose_nlp(text_purpose):
    if not nlp:
        return { # Fallback if spaCy isn't loaded
            'raw_text': text_purpose, 'intent': 'nlp_unavailable', 'visitor_category': 'unknown',
            'entities': [], 'target_entity_text': None, 'error': "spaCy model not loaded"
        }

    doc = nlp(text_purpose)
    
    # Initialize structured data
    structured_data = {
        'raw_text': text_purpose,
        'intent': 'inquiry', # Default intent
        'visitor_category': 'unknown_visitor', # More descriptive default
        'entities': [], # Will store {text: '...', label: '...', lemma: '...'}
        'target_person': None,
        'target_organization': None,
        'target_location_detail': None, # e.g., "Apartment 3B", "third floor"
        'action_verb_lemma': None, # e.g., "see", "deliver", "fix"
        'action_object_text': None # The direct object of the main action verb
    }

    # 1. Named Entity Recognition (NER) - Enhanced
    # We'll also store lemmas of entities for easier rule matching later if needed
    for ent in doc.ents:
        structured_data['entities'].append({
            'text': ent.text,
            'label': ent.label_,
            'lemma': ent.lemma_ # Lemma of the full entity text (might be multiple words)
        })
        if ent.label_ == "PERSON" and not structured_data['target_person']:
            structured_data['target_person'] = ent.text
        if ent.label_ == "ORG" and not structured_data['target_organization']:
            structured_data['target_organization'] = ent.text
        if ent.label_ in ["LOC", "FACILITY", "GPE"] and not structured_data['target_location_detail']: # Facility, GPE might catch apt numbers sometimes
            structured_data['target_location_detail'] = ent.text


    # 2. Lemmatized Keyword-Based Intent & Category (and find main action verb)
    # Define lemmatized keywords for robustness
    delivery_lemmas = {"deliver", "drop", "package", "parcel", "shipment"}
    guest_lemmas = {"visit", "see", "meet", "friend", "guest"}
    service_lemmas = {"maintain", "maintenance", "repair", "fix", "service", "install", "check"}
    emergency_lemmas = {"emergency", "urgent", "help"} # "Help" can be ambiguous

    # Identify primary action and intent
    main_verb_token = None
    for token in doc:
        if token.pos_ == "VERB" and not token.is_stop: # Find a meaningful verb
            if token.lemma_ in delivery_lemmas:
                structured_data['intent'] = 'delivery_request'
                structured_data['action_verb_lemma'] = token.lemma_
                main_verb_token = token
                break # Prioritize first strong intent verb
            elif token.lemma_ in guest_lemmas:
                structured_data['intent'] = 'guest_access_request'
                structured_data['action_verb_lemma'] = token.lemma_
                main_verb_token = token
                break
            elif token.lemma_ in service_lemmas:
                structured_data['intent'] = 'service_request'
                structured_data['action_verb_lemma'] = token.lemma_
                main_verb_token = token
                break
            elif token.lemma_ in emergency_lemmas and not main_verb_token: # Emergency can be an adjective too
                structured_data['intent'] = 'emergency_access' # Or emergency_alert
                structured_data['action_verb_lemma'] = token.lemma_ # might be "help"
                main_verb_token = token
                # Don't break, "emergency" keyword might be more important later

    # If intent still 'inquiry' but emergency keyword found elsewhere
    if structured_data['intent'] == 'inquiry' and any(token.lemma_ in emergency_lemmas for token in doc):
        structured_data['intent'] = 'emergency_alert' # More of an alert than access request
        structured_data['visitor_category'] = 'informant_emergency'


    # 3. Refine Target Entity using Dependency Parsing (if a main verb was found)
    if main_verb_token:
        # Look for direct objects (dobj) or objects of prepositions (pobj)
        for child in main_verb_token.children:
            if child.dep_ == "dobj": # Direct object
                # Check if this child or its subtree corresponds to a known entity or has relevant POS
                # For simplicity, let's take the noun chunk this child belongs to, or the child itself
                obj_text_candidate = child.text
                for chunk in doc.noun_chunks: # Find the noun chunk containing this child
                    if child.i >= chunk.start and child.i < chunk.end:
                        obj_text_candidate = chunk.text
                        break
                structured_data['action_object_text'] = obj_text_candidate
                
                # If we haven't set specific targets yet, try to use this
                if not structured_data['target_person'] and child.ent_type_ == "PERSON":
                    structured_data['target_person'] = child.text
                elif not structured_data['target_organization'] and child.ent_type_ == "ORG":
                    structured_data['target_organization'] = child.text
                break # Assume one primary object for simplicity
            elif child.dep_ == "prep": # Preposition
                for p_child in child.children:
                    if p_child.dep_ == "pobj": # Object of preposition
                        obj_text_candidate = p_child.text
                        for chunk in doc.noun_chunks:
                            if p_child.i >= chunk.start and p_child.i < chunk.end:
                                obj_text_candidate = chunk.text
                                break
                        if not structured_data['action_object_text']: # Prioritize dobj if found
                             structured_data['action_object_text'] = obj_text_candidate

                        if not structured_data['target_person'] and p_child.ent_type_ == "PERSON":
                            structured_data['target_person'] = p_child.text
                        elif not structured_data['target_organization'] and p_child.ent_type_ == "ORG":
                            structured_data['target_organization'] = p_child.text
                        elif not structured_data['target_location_detail'] and p_child.ent_type_ in ["LOC", "FAC", "GPE"]:
                            structured_data['target_location_detail'] = p_child.text
                        # break # May have multiple pobj, let's not break here immediately
    
    # Create a general 'target_entity_text' from specific targets
    if structured_data['target_person']:
        structured_data['target_entity_text'] = structured_data['target_person']
    elif structured_data['target_organization']:
        structured_data['target_entity_text'] = structured_data['target_organization']
    elif structured_data['action_object_text']: # Fallback to general action object
        structured_data['target_entity_text'] = structured_data['action_object_text']
    elif structured_data['target_location_detail']:
        structured_data['target_entity_text'] = structured_data['target_location_detail']


    # 4. Refine Visitor Category based on intent and entities
    if structured_data['intent'] == 'delivery_request':
        if any(ent['label'] == 'ORG' and ent['text'].lower() in ['dhl', 'fedex', 'ups', 'post'] for ent in structured_data['entities']):
            org_name = next((ent['text'] for ent in structured_data['entities'] if ent['label'] == 'ORG' and ent['text'].lower() in ['dhl', 'fedex', 'ups', 'post']), 'generic')
            structured_data['visitor_category'] = f'courier_{org_name.lower()}'
        else:
            structured_data['visitor_category'] = 'courier_generic'
    elif structured_data['intent'] == 'guest_access_request':
        if structured_data['target_person']:
            structured_data['visitor_category'] = 'guest_for_person'
        else:
            structured_data['visitor_category'] = 'guest_general'
    elif structured_data['intent'] == 'service_request':
        if structured_data['target_organization']: # e.g. "Mike from ACME Plumbing"
            structured_data['visitor_category'] = f'service_personnel_{structured_data["target_organization"].replace(" ", "_").lower()}'
        else: # e.g. "I'm the electrician"
            # Try to find service type in noun chunks or entities
            service_type_keywords = {"electrician", "plumber", "technician"}
            found_service_type = None
            for token in doc:
                if token.lemma_ in service_type_keywords:
                    found_service_type = token.lemma_
                    break
            if found_service_type:
                structured_data['visitor_category'] = f'service_{found_service_type}'
            else:
                structured_data['visitor_category'] = 'service_personnel_generic'
    elif structured_data['intent'] == 'emergency_access' or structured_data['intent'] == 'emergency_alert':
        # Could check for keywords like "police", "fire", "ambulance"
        structured_data['visitor_category'] = 'emergency_related'

    # Remove raw_text if you only want the processed fields in the final output for policy
    # final_output = {k: v for k, v in structured_data.items() if k != 'raw_text'}
    # Or keep it, policy module can ignore it. For now, let's keep it for completeness.

    print(f"Enhanced NLP Processed: {structured_data}")
    return structured_data

# Define keyword lists (or import from a config file) - these were inferred from your app.py's NLP logic
delivery_keywords = {"delivery", "package", "parcel", "shipment", "dropping off", "drop off"}
guest_keywords = {"visit", "see", "meet", "friend", "guest"}
service_keywords = {"maintain", "maintenance", "repair", "fix", "service", "install", "check"}
emergency_keywords = {"emergency", "urgent", "help"}