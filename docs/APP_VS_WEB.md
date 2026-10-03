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
| Notifications (11b.10) | "All" and "Unread" are at least 44 px tall on phones | 38 dp | 44 dp, found by the screen tour |
| Messages (11b.10) | Switches: the brand colour when on, grey when off, a white knob | Android's own teal knob | Same as the web |

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
| Paying online (11b.7) | "Pay now" opens the gateway's checkout on the same page | "Pay now" opens that checkout's payment page in a Chrome Custom Tab, signed in for that payment only; back in the app, the status is read from the server | UPI apps open from a browser, not from inside an app (owner's answer 4; checkpoint item 7) |
| Documents (11b.7) | "Download" | "Open" (the phone's PDF viewer) and "Share" (WhatsApp, email, Drive) | Sharing is a native addition |
| Return items (11b.7) | A dialog on the bill | A full screen from the bill, with the same fields, words and limits | A form with a number for each item is easier to fill on a phone as its own screen |
| Statement dates (11b.7) | The browser's date inputs | Android's date picker | The phone's own way to pick a date |
| Push (11b.8) | — | App notifications in three Android channels; the sound while the app is open, with a switch in Messages | Native addition (owner's items 3 and 4) |
| Suggest a better word (11b.8) | A link on every shop page in Hindi and Marathi, filled with the words selected on the page | An entry in Account in Hindi and Marathi; it sends the screen the shop was on before Account, and the shop types the words | A phone has no text selection across a screen and no page footer; the reviewers still get the screen |
| Your profile (11b.8) | Name and language saved together with Save | The name with Save; the language applies at once | Choosing a language on a phone should show it straight away |
| The WhatsApp question (11b.8) | A dialog on the page | Android's own dialog, the same words and buttons | The phone's way to ask |
| Money pages' tab (11b.7) | Bills, statement, payments and returns highlight no bottom tab (the web marks Account only under `/shop/account`) | They open in the Account tab | Each app screen belongs to a tab's stack; Account is where these pages are opened from |

## Not built yet (the next steps match the web screens captured for this comparison)

Built in 11b.7 and matching the web: the "What you owe" card on home; Account's money summary with Pay online; My bills, a bill (paying it, items, returns, credit notes), Statement, My payments and a checkout; bills on an order open the bill.

| Web | Step |
| --- | --- |
| — | Everything the web's shop has is in the app since 11b.8 |

Built in 11b.8 and matching the web: the bell on every page and Notifications; Messages; the WhatsApp question on home; the name on Your profile.

The owner asked for more Account entries (checkpoint item 5): Returns, Delivery addresses, Help, Privacy and data. The web's Account has them too since 11b.8, with the same words. Only the app has the version, "Shop with another distributor", the sound switch and the phone's notification settings.
