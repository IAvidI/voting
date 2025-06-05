# Adaptive Access Control System with Threshold Cryptography

This project is a proof-of-concept (PoC) implementation of an adaptive access control system designed for a smart doorphone scenario. It integrates Natural Language Processing (NLP) for visitor interaction, dynamic policy management influenced by context, and threshold cryptography (Shamir's Secret Sharing) for decentralized access decisions by residents.

The core idea is to move beyond static access control mechanisms by allowing residents to collectively vote on access requests and by dynamically adjusting security parameters based on the analyzed context of the request.

## Project Overview

The system simulates a smart doorphone interaction where:
1.  A **Visitor** participant states their purpose.
2.  An **NLP Module** (using spaCy and rule-based logic) processes this purpose to extract structured information like intent, visitor category, and named entities. 
3.  A **Policy Module** uses this structured NLP output to dynamically determine the parameters for a resident vote (specifically, the threshold `t` of required "Allow" votes). 
4.  A **Cryptographic Voting Module** then manages the voting process:
    * A secret is generated and split into shares using Shamir's Secret Sharing (SSS) based on the number of voting residents (`n`) and the determined threshold (`t`). 
    * Residents (other participants) cast their votes ("Allow", "Deny", "Abstain"). An "Allow" vote signifies contributing their conceptual share.
    * If enough shares are contributed (i.e., "Allow" votes ≥ `t`), the system attempts to reconstruct the secret. 
    * Access is granted or denied based on the successful reconstruction of the secret. 
5.  An **Admin** participant can set up sessions, assign roles (Visitor vs. Resident), monitor the process, and initiate voting rounds.

The project includes a web-based interface built with Flask and SocketIO for real-time interaction and demonstration.

## Features Implemented

* **Role-Based Interaction**: Admin, Visitor, and Resident roles.
* **Session Management**: QR code joining for participants.
* **Real-Time NLP Processing**: Visitor's text input is processed by a lightweight NLP module (spaCy + rules) to extract intent, category, and entities. 
* **Dynamic Policy (Basic)**: The voting threshold (`t_threshold`) is dynamically adjusted based on the NLP-derived context. 
* **Shamir's Secret Sharing (SSS)**:
    * Secret generation and splitting into shares for participating residents. 
    * Collection of "Allow" votes (conceptual shares).
    * Secret reconstruction attempt based on the threshold.
* **Real-Time Voting**: Residents vote, and the system tallies votes to determine access.
* **Admin Dashboard**: For monitoring session status, NLP output, policy decisions, SSS steps, and voting progress.
* **Modular Backend (Python)**:
    * `main_app.py`: Flask routes, SocketIO handlers, session orchestration.
    * `nlp_module.py`: NLP processing logic.
    * `policy_module.py`: Dynamic policy logic.
* **Web-Based UI**: For admin, visitor, and resident interactions.

## Technologies Used

* **Backend**: Python, Flask, Flask-SocketIO
* **NLP**: spaCy (`en_core_web_sm` model)
* **Cryptography**: `pycryptodome` (for Shamir's Secret Sharing)
* **Frontend**: HTML, CSS, JavaScript
* **Real-time Communication**: WebSockets (via Flask-SocketIO)
* **QR Code Generation**: `qrcode` Python library

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/IAvidI/voting.git](https://github.com/IAvidI/voting.git)
    cd voting
    ```
2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install Flask Flask-SocketIO qrcode[pil] spacy pycryptodome
    ```
4.  **Download spaCy model:**
    ```bash
    python -m spacy download en_core_web_sm
    ```
5.  **Run the application:**
    ```bash
    python main_app.py
    ```
    The application will typically be available at `http://localhost:5001` or `http://0.0.0.0:5001`.

## How to Use the Simulation

1.  **Admin View**: Open a browser and navigate to the application's host (e.g., `http://localhost:5001`).
    * Click "Create New Access Session". A QR code and join link will be displayed.
2.  **Participant View (Visitor/Residents)**: Other participants can join by scanning the QR code or using the join link on their devices (e.g., smartphones or other browser tabs).
    * Each participant enters a unique nickname.
3.  **Role Assignment (Admin View)**:
    * The admin sees a list of connected users.
    * The admin clicks "Make Visitor" next to one user to assign them the visitor role. Other connected users automatically become residents (voters).
4.  **Visitor Interaction (Visitor's Device)**:
    * The user assigned as "Visitor" will see an input field to type their purpose of visit.
    * They type their purpose and click "Submit Purpose".
5.  **NLP & Policy (Admin View)**:
    * The admin view will display the visitor's raw purpose and the structured information extracted by the NLP module (intent, category, entities, etc.) using a chip-based display.
    * The "System Thinking Process" log will show how the policy module uses this NLP output to determine the voting threshold `t`.
6.  **Initiate Voting (Admin View)**:
    * The admin sets a timer (in seconds).
    * The admin clicks "Initiate Voting Process".
    * The admin view will log the SSS secret generation and share splitting process.
7.  **Resident Voting (Residents' Devices)**:
    * Residents see the visitor's purpose and the NLP analysis (chip display).
    * They can vote "Allow Entry", "Deny Entry", or "Abstain". An "Allow" vote conceptually contributes their SSS share.
8.  **Tally & Outcome**:
    * Voting ends when the timer expires, all residents have voted, or the admin manually ends it.
    * The server attempts SSS reconstruction if enough "Allow" shares are contributed.
    * The admin view logs the SSS reconstruction attempt and result.
    * All participants (admin, visitor, residents) see the final outcome (Access Granted/Denied).
9.  **New Round (Admin View)**:
    * The admin can click "Start New Round / Reassign Roles" to reset the session for a new scenario.

## Future Work / Potential Enhancements

* **Trust Model Integration**: Develop a dynamic trust scoring mechanism based on interaction history, visitor category, etc., and have it influence the policy module. 
* **Anomaly Detection Module**: Implement basic anomaly detection rules (e.g., unusual request frequency, suspicious NLP output patterns) that can feed into the trust model or directly influence risk assessment. 
* **More Advanced NLP**:
    * Refine intent, category, and entity extraction rules further.
    * Explore more spaCy features (dependency parsing, PhraseMatcher for complex patterns).
    * Consider training a simple custom intent classifier if rule-based logic becomes too complex.
    * Actual Speech-to-Text integration for visitor input (Web Speech API).
* **Enhanced Policy Engine**: More complex and configurable access policies.
* **Security & Usability Evaluation**: Conduct evaluations as outlined in Phase 5 of the paper. 
* **Error Handling & UI Polish**: Continue to improve robustness and user experience.

## Contribution

This project serves as a PoC for my thesis demonstrating the integration of NLP-derived context with dynamic policy and threshold cryptographic voting concepts.

---
