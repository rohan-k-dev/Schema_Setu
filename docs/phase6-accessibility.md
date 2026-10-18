# Phase 6 — Accessibility

## Mobile-First Layout (§41)
- Responsive grid: single column on mobile, 3-column on desktop
- Height adapts: 600px mobile, 700px tablet, 750px desktop
- Scrollable scheme list and chat area

## Touch Targets (§42)
All interactive elements have minimum 44×44px touch areas:
- Voice toggle button: `min-w-[44px] min-h-[44px]`
- Send button: `min-w-[44px] min-h-[44px]`
- Text input: `min-h-[44px]`
- Language selector: `min-w-[44px] min-h-[44px]`
- Language option items: `min-h-[44px]`

## Screen Reader Labels (§44–§46)
- Language selector: `aria-label`, `aria-expanded`, `role="listbox"`
- Voice button: dynamic `aria-label` based on state
- Chat input: `aria-label="Type your message"`
- Scheme cards: `role="article"`, `aria-label` with scheme name
- Status badges: `role="status"`, `aria-label` with eligibility text
- Voice status: `role="status"`, `aria-live="polite"`

## Keyboard Navigation (§43)
- Enter key sends message
- All buttons are focusable
- Language dropdown closes on backdrop click

## Status Labels (§50)
Eligibility badges use text + icon, never color-only:
- ✅ ELIGIBLE: "Matches available criteria" + CheckCircle icon
- ⚠ NEEDS_MORE_INFORMATION: "More information needed" + HelpCircle icon
- ❌ NOT_ELIGIBLE: "Does not match current criteria" + XCircle icon
- ℹ UNVERIFIABLE: "Needs additional verification" + AlertTriangle icon

## Voice-First Usability (§47)
- Voice button is prominently placed (leftmost in input area)
- Voice state indicator shows recording/uploading/transcribing status
- TTS auto-plays responses for voice users
- Text remains always available as fallback

## Files Modified
- `frontend/src/components/ChatInput.tsx` — ARIA labels, touch targets
- `frontend/src/components/SchemeList.tsx` — role attributes, status labels
- `frontend/src/components/LanguageSelector.tsx` — listbox pattern
- `frontend/src/app/page.tsx` — responsive layout, ARIA landmarks
