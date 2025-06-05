import json # For pretty printing dictionaries
from nlp_module import process_visitor_purpose_nlp, NLP_MODEL as spacy_nlp_model

def print_structured_output(text, output):
    print("-" * 50)
    print(f"RAW TEXT INPUT:\n \"{text}\"")
    print("\nSTRUCTURED NLP OUTPUT:")
    # Pretty print the dictionary
    print(json.dumps(output, indent=4))
    print("-" * 50 + "\n")

def main_test_nlp():
    if not spacy_nlp_model:
        print("spaCy model failed to load in app.py. NLP testing cannot proceed.")
        return

    test_phrases = [
        "Hi, DHL delivery for apartment 3B.",
        "Hello, I'm here to visit Sandra Müller.",
        "Good morning, it's Mike from ACME Plumbing, here for the scheduled maintenance in unit 7A.",
        "Is this where Lisa lives? I'm a friend.",
        "Pizza for Mark, order number 123.",
        "I'm supposed to meet Sarah Walker in Apt 2G for a quick consultation, and also drop off this report for the building manager.",
        "Here about the thing.",
        "Got a pakage for Mr. Smoth in #5.",
        "Emergency! There's water leaking rapidly in the hallway near apartment 2C, I need someone to check it immediately!",
        "Hello, I need to see Mr. Anderson about the urgent AC repair in apartment 5C", # Your example that gave specific output
        "Can I speak to the site manager about a broken window?",
        "Dropping off some documents for Mr. Harrison in unit 10.",
        "Need to perform an urgent electrical check in the main lobby."
    ]

    print("Starting NLP Test Run...\n")
    for phrase in test_phrases:
        structured_output = process_visitor_purpose_nlp(phrase)
        print_structured_output(phrase, structured_output)

    print("NLP Test Run Finished.")

if __name__ == "__main__":
    main_test_nlp()