# The shop app against the shop web app

The shop web app is the reference for layout, navigation and behaviour. The Android app differs from it only where it adds something native (push, offline, sharing) or where Android has its own way of doing the same thing. This page lists every difference and the reason for each one. Update it when a screen is added or changed on either side.

**How it was compared (2026-10-03, owner's checkpoint review, item 10):** every shop screen at 360 px. The web side used Playwright against the LAN stack; the app side used the Android 16 emulator set to 360 dp (`adb shell wm density 480`). Both sides were signed in as Ganesh Kirana (Sharma Distributors). Each screen was checked for its elements, their order, the wording and what each tap does.

## Fixed (they weren't deliberate)

| Screen | Web | App before | App now |
| --- | --- | --- | --- |
| Every page inside the shop | The bottom bar stays on category, search, product and order pages | Those pages opened above the tabs, which hid the bar | Each tab has its own stack and the bar stays on every page. The cart is one tap away from anywhere, and its badge updates on every add, change or removal |
| Product | The order box is part of the page, after the details | A box fixed to the bottom of the screen | Part of the page, after the details |
| Product | The free-offer badge appears once | Shown twice | Once |
| Order | The timeline comes before the totals | After the totals | Before the totals |
| After "Place order" | The order opens in Orders | The order opened above the tabs | The order opens in the Orders tab |
| Product, order, category, search | "Shop" in the header on every page; the page's heading (product, order number, category, "Search") in the page | The heading was the header's title, so the product's name and the order number appeared twice; the category's header said "Catalog" | The header shows the distributor's name on every page and the heading is in the page, as on the web |
| Status badges | A dot, a thin ring and medium-weight text | A plain pill | Same as the web |
| Product cards | "Add" is at least 96 px wide | 112 px | 96 px |
| Hindi and Marathi | Headings in Noto Sans Devanagari at medium weight | Regular weight on phones whose own fonts have no medium Devanagari; short labels could lose their last word | The same Noto Sans Devanagari Medium, bundled (ADR-061 item 12); every label shows in full |
| Product cards and the cart | The quantity box is 64 px wide; in the cart the stepper sits on the right | The box stretched across the card and hid the "Last time" note | 64 wide; on the right in the cart |
| Search results | A tap on "Add" while typing closes the phone's keyboard | The keyboard stayed open and covered the bottom bar | "Add", "+" and "−" close the keyboard |

Checked on the emulator after the fixes:
- `mobile/e2e/three-taps.mjs`: search → Add → Cart → Place order, 3 taps (ORD-2026-000060).
- `mobile/e2e/search-keyboard.mjs`: the keyboard stays open while a whole word is typed.

## Kept, and why

| Screen | Web | App | Why |
| --- | --- | --- | --- |
| Header, on every page | "Shop" and the notifications bell | The distributor's name, with Android's back arrow on inner pages | One app serves every distributor, so the header says whose shop this is (the web's address already does). The bell joins every header in 11b.8, as on the web |
| Back links | "Back", "All products" and "Orders" links at the top of inner pages | Android's back arrow and the phone's back button | Android's own back. The web needs the links because a browser's back button is outside the page |
| Search on home and the catalogue | Type in the box, press Enter, and the search page opens | A tap on the box opens the search page with the keyboard already up, and results come as you type | One search box that's never re-created, the fix for the keyboard closing while typing (checkpoint item 1). Search is still one tap, and the taps to a placed order are the same |
| Sign-in | The distributor's name and colours (from the web address); language in a drop-down | "Shop" and the app's colours; the three languages side by side | The app can't know the distributor before sign-in, so the distributor's colours appear after it. The language is the first choice on a new phone, and all three side by side let someone who can't read English find theirs in one tap |
| Lists | — | Pull down to refresh | Android's usual way to reload; "Show more" works as on the web |
| Buttons and steppers | At least 44 px tall | At least 48 dp | Android's touch-target size |

## Not built yet (the next steps match the web screens captured for this comparison)

| Web | Step |
| --- | --- |
| Home: "What you owe" card | 11b.7 |
| Account: "What you owe", "Pay online", My bills, Statement, My payments | 11b.7 |
| Bill links on an order (they open as PDFs until then) | 11b.7 |
| Home: WhatsApp prompt | 11b.8 |
| The bell with the unread count, Notifications (All / Unread, mark all as read, a tap opens the order, bill or payment) | 11b.8 |
| Account: Messages (per event and channel), Your profile | 11b.8 |

The owner asked for these Account entries in the app beyond what the web's Account has today: return requests, saved delivery addresses, WhatsApp consent, privacy and data, help and contacting the distributor, and the app version. The web gets the same Account entries in 11b.8, so both stay the same, except the app version, which only the app has.
