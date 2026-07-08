# Reminders Story Grooming & Routine Design

## Meeting Info
- **Date:** June 3, 2026
- **Duration:** 2h 21m 30s
- **Source:** Raw transcript

## Summary
This meeting focused on grooming user stories for the "Reminders" feature and integrating scheduling capabilities into the existing "Routine/Preset" design. The team defined requirements for reminder creation via app and voice, including validation rules, recurrence, and room-specific playback. Additionally, the team finalized the workflow for scheduling routines, allowing users to set one-time or recurring presets with custom room configurations. Key discussions included handling overlapping events, priority logic between alarms and reminders, and ensuring consistent history logging for all triggered events.

## Keywords
- Reminders
- Routine/Preset Design
- Voice Commands
- Scheduling
- Recurrence
- Room-specific Playback
- IoT Integration
- Event History
- User Permissions
- Conflict Resolution

## Discussion Points

### Reminder Creation and Management
- **App UI:** Users must be able to create, edit, and delete reminders via the app, selecting date, time, recurrence, and specific rooms.
- **Voice Commands:** Users can create reminders via voice. The system must capture intent, message, and schedule accurately. Voice-based editing or deletion of reminders is restricted.
- **Validation:** Previous dates cannot be selected. Triggered one-time reminders should vanish from the active list.
- **Network Handling:** If a network interruption occurs during a save or delete action, the user must re-initiate the action once connectivity is restored.

### Playback and Priority
- **Room Logic:** Reminders created via app can be assigned to single or multiple rooms. Voice-created reminders default to the room where the request originated.
- **Conflict Resolution:** If a routine, reminder, and alarm overlap, the system follows a priority hierarchy: Routine > Reminder > Alarm. Overlapping events may be disabled or deferred to prevent execution conflicts.
- **Media Interruption:** Alarm/Reminder execution takes priority over ongoing AI responses or music playback.

### Routine/Preset Scheduling
- **Integration:** The existing preset flow remains unchanged, with an added "Schedule Routine" step before the summary page.
- **Scheduling Options:** Users can choose "Once" (date/time/room) or "Recurring" (daily/weekly/monthly frequency).
- **Customization:** Users can configure specific IoT settings per room within a scheduled routine. Global room settings apply unless a custom configuration is explicitly set.

### History and Logging
- **Event Tracking:** All triggered reminders, alarms, and routines must be logged in the history page.
- **Accuracy:** Logs must reflect successful executions only. Partial triggers (e.g., due to offline status) should be handled as a whole or not logged as successful.

## Decisions
- Voice commands cannot be used to create or edit "Preset Routines."
- Reminders and alarms are restricted to a maximum of 30 days in the future for scheduling.
- Any user profile (Admin, Family, Guest) can create, edit, or delete alarms, reminders, and presets.
- If a user selects TalkBack via speaker or phone, the response must always be delivered via speaker.

## Action Items

| Task | Owner | Due | Status |
| :--- | :--- | :--- | :--- |
| Finalize reminder/alarm priority logic for overlapping events | Not specified | | pending |
| Implement history logging for all triggered events | Not specified | | pending |
| Update UI design to include "Schedule" icon in preset listing | Not specified | | pending |
| Define fallback response messages for successful reminder/alarm sets | Not specified | | pending |

## Pending Tasks
- Define specific error handling for network interruptions during reminder saves.
- Finalize the "Stop" functionality for recurring reminders (toggle vs. delete).
- Implement the 30-day limit validation for scheduling.
- Ensure history logs distinguish between user-created and system-triggered events.

## Completed Tasks
- None explicitly recorded.

## Open Questions
- How should the system handle "Stop" requests for recurring reminders—should it delete the entire series or just disable the next occurrence?
- Should there be a hard limit on the number of rooms selectable for a single reminder?
- How to handle "Same time/Same date" duplicate reminder creation requests?
