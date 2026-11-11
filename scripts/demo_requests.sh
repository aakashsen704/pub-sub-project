#!/usr/bin/env bash
# Runs the full demo sequence against a running broker + 3 subscribers using curl.
# Usage: ./scripts/demo_requests.sh [broker_url]     (default http://localhost:8000)
# Watch the three subscriber terminals while this runs.
BROKER="${1:-http://localhost:8000}"

post() { curl -s -X POST "$BROKER$1" -H "Content-Type: application/json" -d "$2"; echo; echo; }
step() { echo "------------------------------------------------------------"; echo "$1"; echo "------------------------------------------------------------"; read -r -p "(press Enter to run) " _; }

step "1. Register student_A, student_B, student_C"
post /subscribe '{"subscriber_id": "student_A", "callback_url": "http://localhost:5001/notify"}'
post /subscribe '{"subscriber_id": "student_B", "callback_url": "http://localhost:5002/notify"}'
post /subscribe '{"subscriber_id": "student_C", "callback_url": "http://localhost:5003/notify"}'

step "2. View the subscriber registry"
curl -s "$BROKER/subscribers"; echo; echo

step "3. UNICAST -> student_A only"
post /publish '{"event_type": "fee_reminder", "message": "Your fee payment is due tomorrow.", "mode": "unicast", "recipients": ["student_A"]}'

step "4. MULTICAST -> student_A and student_C"
post /publish '{"event_type": "hackathon_update", "message": "Hackathon registration closes tomorrow.", "mode": "multicast", "recipients": ["student_A", "student_C"]}'

step "5. BROADCAST -> everyone"
post /publish '{"event_type": "general_announcement", "message": "Tomorrow is a holiday for everyone.", "mode": "broadcast"}'

echo "Optional: stop one subscriber (Ctrl+C in its terminal) and broadcast again to see the failure report,"
echo "then unregister with:  curl -X DELETE $BROKER/unsubscribe/student_B"
