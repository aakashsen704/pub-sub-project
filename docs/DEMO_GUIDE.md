# Demo Video Guide (max 5 minutes, target 4:40)

Record your screen with all four terminals visible plus a browser with Swagger UI (http://localhost:8000/docs).
No PowerPoint needed – show the real running application.

| Time | Section | What to say / show |
|---|---|---|
| 0:00–0:20 | **Group introduction** | Names of group members, course, project title. |
| 0:20–1:20 | **What the system does** | Explain Publish–Subscribe: publishers send events to a broker, subscribers register callbacks, the broker pushes events to them. Name the three modes: unicast (one), multicast (selected group), broadcast (all). Mention REST + HTTP POST callbacks. |
| 1:20–2:20 | **Architecture diagram** | Show `docs/architecture.png`. Point out: publisher → `/publish` (blue arrow); broker + in-memory registry; recipient selection; HTTP POST `/notify` callbacks (green arrows) to three independent subscribers on 5001/5002/5003. |
| 2:20–4:20 | **Live demo** | 1) Show the 4 terminals running (broker + 3 subscribers). 2) Register A, B, C in Swagger. 3) `GET /subscribers`. 4) Unicast → A only. 5) Multicast → A and C. 6) Broadcast → all three. 7) If time: stop B, broadcast, show `failed` for B but A/C still receive. |
| 4:20–4:40 | **Takeaway** | e.g. "Decoupled communication over HTTP, group communication patterns, and handling partial failures in a distributed system." |

## Request bodies to paste into Swagger UI

Register:
```json
{"subscriber_id": "student_A", "callback_url": "http://localhost:5001/notify"}
{"subscriber_id": "student_B", "callback_url": "http://localhost:5002/notify"}
{"subscriber_id": "student_C", "callback_url": "http://localhost:5003/notify"}
```
Unicast:
```json
{"event_type": "fee_reminder", "message": "Your fee payment is due tomorrow.", "mode": "unicast", "recipients": ["student_A"]}
```
Multicast:
```json
{"event_type": "hackathon_update", "message": "Hackathon registration closes tomorrow.", "mode": "multicast", "recipients": ["student_A", "student_C"]}
```
Broadcast:
```json
{"event_type": "general_announcement", "message": "Tomorrow is a holiday for everyone.", "mode": "broadcast"}
```

Tips: keep terminal fonts large, show the subscriber terminals right after each publish, and re-register
the subscribers if you restart the broker (the registry is in memory).
