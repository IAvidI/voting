import spacy
from spacy.matcher import Matcher

# Load the spaCy model once when this module is imported
NLP_MODEL = None
try:
    NLP_MODEL = spacy.load("en_core_web_sm")
    print("spaCy model 'en_core_web_sm' loaded successfully by nlp_module.")
except OSError:
    print("ERROR in nlp_module: spaCy model 'en_core_web_sm' not found. "
          "Please run: python -m spacy download en_core_web_sm")

# Initialize Matcher only if NLP_MODEL is loaded
matcher = None
if NLP_MODEL:
    matcher = Matcher(NLP_MODEL.vocab)
    # More robust apartment/unit pattern
    # Catches: apt 3b, apartment 3B, unit 7-A, #5, apt.4
    apt_pattern = [
        {"LOWER": {"IN": ["apartment", "apt", "apt.", "unit", "#", "flat"]}},
        {"IS_PUNCT": True, "OP": "?"}, # Optional punctuation like . after apt
        {"IS_SPACE": True, "OP": "?"}, # Optional space
        {"TEXT": {"REGEX": "^[0-9A-Za-z]+([\\-/]?[0-9A-Za-z]+)*$"}} # Number, letter, or combo like 3B, 7-A, 101
    ]
    matcher.add("APARTMENT_UNIT_PATTERN", [apt_pattern])
else:
    print("Matcher not initialized because spaCy model failed to load.")


# Define lemmatized keyword lists (moved to global for clarity)
DELIVERY_LEMMAS = {"deliver", "drop", "package", "parcel", "shipment", "pizza", "food", "order"} # Added food/order
GUEST_LEMMAS = {"visit", "see", "meet", "friend", "guest", "consultation"} # Added consultation
SERVICE_LEMMAS = {"maintain", "maintenance", "repair", "fix", "service", "install", "check", "electrician", "plumber", "technician"}
EMERGENCY_LEMMAS = {"emergency", "urgent", "help"} # "help" can be ambiguous, use with care

# Keywords for specific visitor categories (can be expanded)
KNOWN_COURIERS_LOWER = {"dhl", "fedex", "ups", "post"}


def process_visitor_purpose_nlp(text_purpose):
    if not NLP_MODEL or not matcher: # Check both
        return {
            'raw_text': text_purpose, 'intent': 'nlp_unavailable', 'visitor_category': 'unknown_visitor',
            'entities': [], 'target_entity_text': None, 'error': "spaCy model or Matcher not loaded"
        }

    doc = NLP_MODEL(text_purpose)
    lower_purpose = text_purpose.lower() # Define it once for reuse

    structured_data = {
        'raw_text': text_purpose,
        'intent': 'inquiry', # Default
        'visitor_category': 'unknown_visitor',
        'entities': [],
        'target_person': None,
        'target_organization': None,
        'target_location_detail': None,
        'action_verb_lemma': None,
        'action_object_text': None,
        'target_entity_text': None,
        'urgency': 'normal' # New field for urgency
    }

    # --- 0. Run Matcher for specific patterns first (e.g., apartment/unit) ---
    matcher_matches = matcher(doc)
    found_locations_from_matcher = []
    for match_id, start, end in matcher_matches:
        span = doc[start:end]
        if NLP_MODEL.vocab.strings[match_id] == "APARTMENT_UNIT_PATTERN":
            found_locations_from_matcher.append(span.text)
            if not structured_data['target_location_detail']: # Take the first one for now
                structured_data['target_location_detail'] = span.text
                print(f"Matcher found APARTMENT_UNIT: {span.text}")
                # Add to entities if desired, or just use for target_location_detail
                structured_data['entities'].append({'text': span.text, 'label': 'LOC_APT_CUSTOM', 'lemma': span.lemma_})


    # --- 1. Named Entity Recognition (NER) ---
    # Store all NER entities. We'll use them for refining category and targets.
    processed_entities = []
    for ent in doc.ents:
        # Simple title merging (can be expanded)
        text_to_add = ent.text
        if ent.start > 0 and doc[ent.start - 1].text.lower() in ["mr.", "ms.", "mrs.", "dr."]:
            text_to_add = doc[ent.start - 1].text + " " + ent.text
        
        # Avoid adding if it's part of a location already fully captured by matcher
        is_part_of_matcher_loc = False
        if structured_data['target_location_detail']:
            # Check if ent.text is a substring of the matcher location AND the matcher location is more specific
            # This simple check might need refinement if NER gives a broader LOC that contains the matcher loc
            if ent.text in structured_data['target_location_detail'] and len(ent.text) < len(structured_data['target_location_detail']):
                 pass # Don't add if it's a less specific part of what matcher found
            elif ent.text == structured_data['target_location_detail'] and any(e['label'] == 'LOC_APT_CUSTOM' for e in structured_data['entities']):
                 pass # Don't add if matcher already added it as custom
            else:
                processed_entities.append({'text': text_to_add, 'label': ent.label_, 'lemma': NLP_MODEL(text_to_add)[0].lemma_ if text_to_add else ent.lemma_})
        else:
            processed_entities.append({'text': text_to_add, 'label': ent.label_, 'lemma': NLP_MODEL(text_to_add)[0].lemma_ if text_to_add else ent.lemma_})

    structured_data['entities'] = processed_entities

    # --- 2. Identify Main Action Verb and Initial Intent/Urgency ---
    # Intent detection with priority: emergency > service > delivery > guest > inquiry
    intent_set = False
    if any(lemma in lower_purpose for lemma in EMERGENCY_LEMMAS):
        structured_data['intent'] = 'emergency_alert'
        structured_data['urgency'] = 'high'
        structured_data['action_verb_lemma'] = 'alert' # Default for alert
        for token in doc: # Try to find a more specific verb
            if token.lemma_ in EMERGENCY_LEMMAS and token.pos_ == "VERB": structured_data['action_verb_lemma'] = token.lemma_; break
            if token.lemma_ in SERVICE_LEMMAS and token.pos_ == "VERB": structured_data['action_verb_lemma'] = token.lemma_; break # e.g. "urgent repair"
        intent_set = True

    if not intent_set and any(lemma in lower_purpose for lemma in SERVICE_LEMMAS):
        structured_data['intent'] = 'service_request'
        structured_data['action_verb_lemma'] = next((token.lemma_ for token in doc if token.pos_ == "VERB" and token.lemma_ in SERVICE_LEMMAS), 'service')
        if "urgent" in lower_purpose: structured_data['urgency'] = 'high'
        intent_set = True
    
    if not intent_set and any(lemma in lower_purpose for lemma in DELIVERY_LEMMAS):
        structured_data['intent'] = 'delivery_request'
        structured_data['action_verb_lemma'] = 'deliver'
        if "food" in lower_purpose or "pizza" in lower_purpose: structured_data['urgency'] = 'medium'
        intent_set = True

    if not intent_set and any(lemma in lower_purpose for lemma in GUEST_LEMMAS):
        structured_data['intent'] = 'guest_access_request'
        structured_data['action_verb_lemma'] = next((token.lemma_ for token in doc if token.pos_ == "VERB" and token.lemma_ in GUEST_LEMMAS), 'visit')
        intent_set = True
    
    # If intent is still 'inquiry' but was set to 'high' urgency, it's likely an emergency alert
    if structured_data['intent'] == 'inquiry' and structured_data['urgency'] == 'high':
        structured_data['intent'] = 'emergency_alert'

    # --- 3. Refine Target Person, Organization, Location (using NER and some context) ---
    # Prioritize entities found by NER for these roles
    for ent in structured_data['entities']:
        if ent['label'] == "PERSON" and not structured_data['target_person']:
            structured_data['target_person'] = ent['text']
        elif ent['label'] == "ORG" and not structured_data['target_organization']:
            structured_data['target_organization'] = ent['text']
        # target_location_detail is primarily set by Matcher, but NER LOC/FAC can be a fallback
        elif ent['label'] in ["LOC", "FACILITY", "GPE"] and not structured_data['target_location_detail']:
             # Avoid general locations if a specific unit was already found by matcher
            if not any(custom_loc_ent['label'] == 'LOC_APT_CUSTOM' and custom_loc_ent['text'] == ent['text'] for custom_loc_ent in structured_data['entities']):
                 structured_data['target_location_detail'] = ent['text']
    
    # Extract visitor's name and org if "I'm X from Y" pattern
    visitor_name_identified = None
    visitor_org_identified = None
    for i, token in enumerate(doc):
        if token.lemma_ == "from" and i > 0:
            prev_token_or_chunk = doc[i-1].text
            # Check if previous token is a PERSON entity (potential visitor name)
            for ent in structured_data['entities']:
                if ent['text'] == prev_token_or_chunk and ent['label'] == 'PERSON':
                    visitor_name_identified = ent['text']
                    break
            # Check if object of "from" is an ORG entity (visitor's org)
            for child in token.children:
                if child.dep_ == "pobj":
                    for ent in structured_data['entities']:
                        if ent['text'] == child.text and ent['label'] == 'ORG':
                            visitor_org_identified = ent['text']
                            break
                    if visitor_org_identified: break
        if visitor_name_identified and visitor_org_identified: break
    
    # If visitor identified, ensure they are not the primary target_person
    if visitor_name_identified and structured_data['target_person'] == visitor_name_identified:
        structured_data['target_person'] = None # Clear it, look for another target

    # If an ORG was identified as visitor's ORG, it's not the target_organization for the visit itself
    if visitor_org_identified and structured_data['target_organization'] == visitor_org_identified:
        structured_data['target_organization'] = None


    # --- 4. Refine Visitor Category based on Intent and Entities ---
    if structured_data['intent'] == 'delivery_request':
        is_known_courier = False
        for ent in structured_data['entities']:
            if ent['label'] == 'ORG' and ent['text'].lower() in KNOWN_COURIERS_LOWER:
                structured_data['visitor_category'] = f'courier_{ent["text"].lower()}'
                is_known_courier = True
                break
        if not is_known_courier:
            if "food" in lower_purpose or "pizza" in lower_purpose: # Check again for food
                 structured_data['visitor_category'] = 'food_delivery_generic'
                 if structured_data['target_organization']: # e.g. "Pizza Place"
                     structured_data['visitor_category'] = f'food_delivery_{structured_data["target_organization"].replace(" ","_").lower()}'
            else:
                 structured_data['visitor_category'] = 'courier_generic'

    elif structured_data['intent'] == 'guest_access_request':
        if "friend" in lower_purpose:
            structured_data['visitor_category'] = 'guest_friend'
        elif structured_data['target_person']:
            structured_data['visitor_category'] = 'guest_for_person'
        else:
            structured_data['visitor_category'] = 'guest_general'

    elif structured_data['intent'] == 'service_request':
        service_org = None
        for ent in structured_data['entities']:
            if ent['label'] == 'ORG': # Could be visitor's ORG
                # A simple check: if "from [ORG]" or ORG name is near service keywords
                if f"from {ent['text'].lower()}" in lower_purpose or any(lemma in ent['text'].lower() for lemma in SERVICE_LEMMAS):
                    service_org = ent['text']
                    break
        if service_org:
            structured_data['visitor_category'] = f'technician_{service_org.replace(" ", "_").lower()}'
        else: # Check for explicit roles like "electrician" if no ORG found
            found_role_keyword = None
            for lemma in SERVICE_LEMMAS:
                if lemma in lower_purpose and lemma not in {"service", "repair", "fix", "check", "maintain", "maintenance"}: # avoid generic service verbs
                    found_role_keyword = lemma
                    break
            if found_role_keyword:
                structured_data['visitor_category'] = f'technician_role_{found_role_keyword}'
            else:
                structured_data['visitor_category'] = 'service_personnel_generic'

    elif structured_data['intent'] == 'emergency_alert':
         structured_data['visitor_category'] = 'informant_emergency' # Person reporting
    elif structured_data['intent'] == 'emergency_access':
         structured_data['visitor_category'] = 'emergency_services' # Assumed actual services


    # --- 5. Refine Action Object and Consolidate Target Entity Text ---
    # This part attempts to find the object of the main action verb if identified.
    action_verb_node = None
    if structured_data['action_verb_lemma']:
        for token in doc:
            if token.lemma_ == structured_data['action_verb_lemma'] and token.pos_ == "VERB":
                action_verb_node = token
                break
    
    if action_verb_node:
        for child in action_verb_node.children:
            if child.dep_ in ("dobj", "attr"): # Direct object or attribute
                # Prefer noun chunks for more complete object text
                obj_candidate_text = child.text
                for chunk in doc.noun_chunks:
                    if child.i >= chunk.start and child.i < chunk.end:
                        obj_candidate_text = chunk.text; break
                structured_data['action_object_text'] = obj_candidate_text
                break # Take first one
            elif child.dep_ == "prep": # Check prepositional objects
                for p_child in child.children:
                    if p_child.dep_ == "pobj":
                        p_obj_candidate_text = p_child.text
                        for chunk in doc.noun_chunks:
                            if p_child.i >= chunk.start and p_child.i < chunk.end:
                                p_obj_candidate_text = chunk.text; break
                        if not structured_data['action_object_text']: # Only if dobj not found
                            structured_data['action_object_text'] = p_obj_candidate_text
                        # If this pobj is a person/org/loc, it could also be a target
                        if p_child.ent_type_ == "PERSON" and not structured_data['target_person']:
                            structured_data['target_person'] = p_child.text
                        elif p_child.ent_type_ == "ORG" and not structured_data['target_organization']:
                            structured_data['target_organization'] = p_child.text
                        # Location detail is primarily from Matcher or NER, but pobj can refine
                        elif p_child.ent_type_ in ["LOC","FAC","GPE"] and not structured_data['target_location_detail']:
                             structured_data['target_location_detail'] = p_obj_candidate_text
                        break # Take first pobj for simplicity in this branch
                if structured_data['action_object_text']: 
                    break
        
        # This logic should also try to update target_person/org/location if the object is an entity
        for child in action_verb_node.children:
            if child.dep_ in ("dobj", "attr", "pobj"): # pobj if prep follows verb directly
                obj_text = ""
                # Attempt to get full noun chunk for the object
                for chunk in doc.noun_chunks:
                    if child.i >= chunk.start and child.i < chunk.end: # child is part of this chunk
                        obj_text = chunk.text
                        break
                if not obj_text: obj_text = child.text # Fallback to single token

                structured_data['action_object_text'] = obj_text

                # If this object is an entity, it could be a more specific target
                for ent in structured_data['entities']:
                    if ent['text'] == obj_text: # Or 'in obj_text' for partial matches
                        if ent['label'] == "PERSON" and not structured_data['target_person']:
                            structured_data['target_person'] = ent['text']
                        elif ent['label'] == "ORG" and not structured_data['target_organization']:
                             # Avoid setting visitor's ORG as target if already known
                            if ent['text'] != visitor_org_identified:
                                structured_data['target_organization'] = ent['text']
                        elif ent['label'] in ["LOC","FAC","GPE","LOC_APT_CUSTOM"] and not structured_data['target_location_detail']:
                            structured_data['target_location_detail'] = ent['text']
                        break 
                if structured_data['action_object_text']: break # Take first main object found

    # --- 6. Consolidate Final 'target_entity_text' ---
    # (Your existing consolidation logic - ensure it makes sense with refined targets)
    # Priority: Person > Location (especially for service/delivery) > Org > Action Object
    if structured_data['target_person']:
        structured_data['target_entity_text'] = structured_data['target_person']
    elif structured_data['target_location_detail']:
        structured_data['target_entity_text'] = structured_data['target_location_detail']
    elif structured_data['target_organization'] and structured_data['target_organization'] != visitor_org_identified: # Don't use visitor's own org as target
        structured_data['target_entity_text'] = structured_data['target_organization']
    elif structured_data['action_object_text']:
        # Check if action_object_text is already one of the primary targets to avoid redundancy
        if structured_data['action_object_text'] not in [structured_data['target_person'], structured_data['target_location_detail'], structured_data['target_organization']]:
            structured_data['target_entity_text'] = structured_data['action_object_text']
    
    # If target_entity_text is still None, but there's a prominent entity related to the intent
    if not structured_data['target_entity_text'] and structured_data['entities']:
        if structured_data['intent'] == 'guest_access_request' and any(e['label']=='PERSON' for e in structured_data['entities']):
            structured_data['target_entity_text'] = next((e['text'] for e in structured_data['entities'] if e['label']=='PERSON'), None)
        # Add more fallbacks if needed


    print(f"Refined NLP Processed: {structured_data}")
    return structured_data