# crowD testing guide

How to start crowD, what every part does, and how to test each feature, including on a phone. It assumes you have never seen the project. Run commands from the project folder unless told otherwise.

## 1. What crowD is, in one minute

crowD guides people through an event space (a festival, a stadium) so queues stay short and everyone gets out fast, especially in an emergency.

The pieces:

| Piece | What it is | Where |
|---|---|---|
| Venue | A map made of zones (areas), gates (connections between zones, with a width) and places (exits, food, toilets, stages) | `venues/*.json` |
| Scenario | A crowd and what happens to it: how many people, where they start, where they want to go, timed events | `scenarios/*.json` |
| Planner | The algorithm that decides which gate each person should head for next | `core/` |
| Simulator | Fake people who walk the venue, queue at gates and (some) follow the app | `sim/` |
| Server | Runs events, serves the web pages, talks to phones | `server/` |
| Control room | The organiser page: live map, switch to evacuation, close gates, run several events | `/live.html` |
| Attendee app | The phone page: your instruction, your route on the map | `/app.html` |
| Venue editor | Draw your own venue in the browser | `/editor.html` |
| Run viewer | Replay saved simulation runs | `/viewer.html` |

Words you will see:
- **Event (session):** one running simulation with a short join code, for example `DEMO`.
- **Join code:** what an attendee types to enter an event. Not case sensitive.
- **Mode:** `normal`, `egress` (everyone leaving) or `evacuation` (emergency, go to the nearest safe place).
- **Guest:** a real person (you, on your phone) added to the simulated crowd.
- **Planner:** `baseline` (simple shortest path), `queue-aware` (avoids long queues), `flow` (best possible clearance time, used for evacuation), `adaptive` (flow in evacuation, queue-aware otherwise).

Important: the crowd is simulated. Your phone is one real person among thousands of fake ones. That is how you can test everything without a real crowd.

## 2. Setup

Install once (macOS): `brew install uv node`

Then:

```
./run.sh
```

This installs packages, builds the web pages and starts the server at http://localhost:8000. Leave it running. The terminal will print:
- an admin password on first start, like `created operator account 'admin' with password: Hfr8r66LH7ff`. Copy it. It is only printed once. (To choose your own, set `CROWD_ADMIN_PASSWORD=yourpassword` before `./run.sh`.)
- a line saying the demo event is running with code `DEMO`
- the address to use on your phone

Other ways to start:
- `CROWD_AUTH=off ./run.sh` turns sign in off. Handy for quick tests, never for anything shared.
- `PORT=9000 ./run.sh` uses another port.
- `./run.sh dev` runs the page editor with hot reload at http://localhost:5173 (use that address instead of :8000).
- `docker compose up --build` runs it in Docker.

Lost the admin password: stop the server, delete `data/users.json`, start again. A new admin is created and printed.

## 3. Run the automated tests first

```
uv run pytest            # Python: about 180 tests
cd viz && npm test       # page logic tests
npx tsc --noEmit         # type check
cd ..
```

All should pass. If something fails here, fix that before testing by hand.

## 4. Sign in

1. Open http://localhost:8000/live.html. You are sent to the sign in page.
2. Enter `admin` and the password from the terminal.
3. You land back in the control room. "Sign out" is in the top bar.

Checks:
- A wrong password shows an error. Five wrong tries in a row block that address for a few minutes.
- Add a read-only account: `uv run python -m crowd_server.auth add watcher --role viewer`. Sign in as `watcher`: you can watch events but starting or stopping one shows an error.
- Other account commands: `python -m crowd_server.auth list` and `remove NAME`.

## 5. The control room (the organiser)

Open http://localhost:8000/live.html.

What you see:
- **The map.** Each zone is coloured by how full it is (empty to full, up to its limit). The number is how many people are in or passing through. Orange bubbles are people waiting to cross a gate. Blue dashes are people crossing. A red cross is a closed gate.
- **Events card.** All running events. `DEMO` is there. The big code is what attendees type. Click an event to switch to it. "Stop this event" removes it.
- **Mode.** Normal, Egress, Evacuate.
- **Pause, Restart, speed.** Speed is simulated seconds per real second (1x to 120x).
- **Right now.** Counts: people, out of the venue, still moving, waiting at gates, phones joined, queue switches, redirected.
- **Longest queues** and **Closed gates.**

Test each feature:

| Feature | Steps | Expected |
|---|---|---|
| Live map | Open the page | Pill says `live`, the map moves, "Still moving" counts down |
| Evacuation | Press Evacuate, press it again within 3 seconds (it asks to confirm) | Mode goes red, everyone heads to the nearest safe place (exits and the assembly point) |
| Close a gate | Hover the map until the cursor becomes a pointer on a gate, click | Red cross appears, gate listed under Closed gates, queues reroute. Press Reopen to undo |
| Pause / speed | Press Pause, change speed to 60x | Map freezes, then runs faster |
| Restart | Press Restart | Clock goes back to 0, same join code |
| Run finished | Wait (use 120x) | A note says everyone is out |
| Several events | Open "Start a new event", pick scenario `entry-rush`, press Start | A second event appears with its own code. Click between the two |
| Stop an event | Select one, press "Stop this event", confirm | It disappears. Phones in it lose connection |
| Compare planners | Start the same scenario twice, once with `baseline`, once with `adaptive`, at 120x | Adaptive finishes sooner when the venue has choices |

Starting a new event, the options:
- **Name:** optional label.
- **Venue / Scenario / Planner / People:** what to simulate and how big.
- **Let phones follow simulated people (demo):** lets an attendee watch what a simulated person's phone would show.
- **Record this event to a file:** saves the log to `runs/` for the run viewer.

## 6. The scenarios (the situations you can simulate)

Every file in `scenarios/` appears in the control room. All use the example venue.

| Scenario | People | What it tests | What to watch for |
|---|---|---|---|
| `egress-end-of-night` | 8,000 | Headline act ends, everyone leaves | Biggest queues at the stage gate and the narrow south exit gate |
| `stage-change` | 8,000 | Crowd spreads out to food, toilets, other places | Mostly smooth, one route per place |
| `evacuation-blocked-exit` | 8,000 | Evacuation at 5 minutes with the south exit lane closed | Everyone redirected to other exits |
| `entry-rush` | 6,000 | People arrive over 20 minutes, ramping up | Gate plaza fills, people spread inside |
| `gate-failure-egress` | 8,000 | South exit lane fails at 4 minutes, reopens at 15 | Planner reroutes to the north exit and back |
| `low-adoption-evacuation` | 8,000 | Only 10% have the app, low compliance | Shows how much the app helps when few use it |
| `meet-up` | 4,000 | 90% in groups of about 4, all going to the meeting point | Groups stay together |
| `food-court-closure` | 6,000 | Food court access closed for 10 minutes | Traffic reroutes or waits |
| `dense-dispersal` | 14,000 | Very dense stage front, one narrow way out | Highest crowd density (crush risk) |

Also available for any venue (including ones you draw): `auto-egress`.

Command line version (no browser): 

```
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/gate-failure-egress.json --planner adaptive
```

It prints numbers like `arrived_share` (1.0 is everyone arrived), `clearance_s` (time until the last person arrived), `travel_time_p95_s` (the slow 5%), `peak_density_pp_m2` (people per square metre, above about 4 is dangerous) and `peak_queue`. Compare `--planner baseline` against `--planner adaptive`. Expected results are in `docs/scenarios.md`.

Run the whole benchmark: `uv run python -m crowd_sim.bench`.

## 7. The attendee app (the phone view)

### 7.1 On the computer first

1. Open http://localhost:8000/app.html?s=DEMO
2. The code `DEMO` is filled in. Press Continue.
3. Choose where you are ("Main field") and where you want to go ("Nearest safe exit" or "Food"). Press Start.

You now see:
- **The instruction card:** "Go to [gate]", "Wait for [gate], about N people ahead", "Crossing [gate]", or "You're at [place]".
- **The map** with a dashed arrow from your zone through the next gate into the next zone.
- **Facts:** where you are, where you are going, the mode, group size.
- **Change destination** and **Leave.**

Tests:

| Feature | Steps | Expected |
|---|---|---|
| Bad code | Type `NOPE1` | "no event with that code" |
| Guidance | Start from Main field to Food | Instruction and arrow towards the food court gate |
| Evacuation on the phone | In the control room press Evacuate (twice) | Red banner "EVACUATION. Follow the route shown." within a few seconds, the arrow turns red and points to the nearest safe place |
| Closed gate | Close a gate in the control room | App lists "[gate] is closed" and the route changes |
| Change destination | Pick another destination | Instruction changes |
| Stays joined | Refresh the page | You are still in |
| Leave | Press Leave | Back to the join screen. Control room "phones joined" drops by one |
| Watch a simulated person | Leave, enter `DEMO`, scroll to "Or follow a simulated person", pick one | You see what a simulated person's phone shows. Pick one "in a group" to see "Your group of N moves together" |
| Groups | In the control room use the `meet-up` scenario with demo people on | Group members arrive together |

A tip: use a different browser window or private window as a second phone. The control room shows "Phones joined: 2".

### 7.2 Telling the app where you are

There are three ways, and you can switch between them.

1. **Chosen at join.** The zone you pick when you press Start. The simulation then moves you along the route as if you were walking.
2. **Tap on the map.** Press "Set my position on the map", then tap a zone. You are moved there. This always works, with or without GPS. Use it to simulate walking: tap a zone, wait for the instruction, tap the next zone it names.
3. **Real GPS.** Switch on "Use my phone's location". The phone sends its position every 2 seconds. The server turns it into a zone. The status line says what happened:
   - `Located: [zone]` working
   - "Location too vague here" accuracy worse than 50 m, fix ignored
   - "outside the venue" more than 80 m from the venue, fix ignored
   - "Location permission was denied" allow location for the page in browser settings

A zone change needs two fixes in a row and a small margin from the border, so standing on a gate does not flicker between zones.

When you use tap or GPS, the simulation stops moving you (you are "external"). You still count in zone totals and in the planner. To go back to simulated movement, switch the location checkbox off.

The important catch: GPS only means something if the venue knows where on Earth it is. That is the **anchor** (latitude, longitude and rotation of the venue's (0, 0) point). The example venue has an illustrative anchor in Sydney (Centennial Parklands area). You are not standing there, so a real GPS fix from your desk will say you are outside the venue. To test GPS, use one of the options in section 8.

## 8. Testing on a real phone

### 8.1 Connect it

1. Phone and computer on the same Wi-Fi.
2. `./run.sh` prints an address like `http://192.168.1.20:8000/app.html?s=DEMO`. Type it into the phone browser.
3. If it will not load: allow incoming connections for the terminal or Python in the Mac firewall, check both devices are on the same network (not a guest network), and make sure you used the IP, not `localhost`.
4. You can add it to the home screen (Share, Add to Home Screen) to run it like an app.

This gives you everything except GPS, because phones only allow location on HTTPS pages or localhost. Guidance, evacuation banner, tap-on-map, destinations and leaving all work over plain `http`.

### 8.2 Get real GPS working

Pick one.

**Option A: HTTPS tunnel (easiest and closest to real).** Run in a second terminal:

```
npx cloudflared tunnel --url http://localhost:8000
```

(or `ngrok http 8000`). It prints an `https://...` address. Open `https://.../app.html?s=DEMO` on the phone. GPS now works. Treat the address as public while it runs: sign in is on for organisers, but anyone with the link can join the event.

**Option B: Android Chrome flag.** On the phone open `chrome://flags`, search "Insecure origins treated as secure", add `http://192.168.1.20:8000`, enable, relaunch.

**Option C: No phone at all.** In desktop Chrome open the app, press F12, then the three dots, More tools, Sensors. Under Location choose Override and enter a latitude and longitude. This is the fastest way to prove the GPS-to-zone logic.

### 8.3 Make GPS land inside the venue

The phone must be near the venue's anchor. Either:

- **Move the anchor to where you are** (best for a real walk test). In the venue editor (`/editor.html`), open the example venue (Open venue...), find "Real-world position (optional)" in the right panel, enter your current latitude and longitude, and Save. Your spot is now local (0, 0), the corner of the gate plaza. The example venue is about 260 m wide (x from -60 to 200) and 120 m tall, so walking east moves you through the gate plaza, then the main field, and so on. Find your latitude and longitude from your phone's maps app by long-pressing your location. Save under a new id (for example `my-test`) so you do not change the shipped example, then start an event on it with the `auto-egress` scenario.
- **Rotation** is how far the venue's y axis (its "up") is turned clockwise from north. Leave it at 0 for a north-up venue.
- Or **use the DevTools override** (option C) with coordinates near the example anchor (latitude -33.8975, longitude 151.2300). Adding 0.0009 to the latitude moves you about 100 m north; adding 0.0011 to the longitude moves you about 100 m east.

Check: switch on "Use my phone's location". After a few seconds you should see `Located: [zone]`. Walk to another zone and it should change after two fixes. The control room still counts you as a phone that joined.

### 8.4 A good phone test script (10 minutes)

1. Control room on the laptop, `DEMO` selected, speed 5x.
2. Phone: join `DEMO`, pick "Main field" and "Nearest safe exit", press Start.
3. Confirm the instruction card and arrow. Confirm "Phones joined: 1" on the laptop.
4. Laptop: Evacuate (twice). Phone: red banner within a few seconds, route to the nearest safe place.
5. Laptop: close the gate the phone's arrow points at. Phone: route changes, closed gate listed.
6. Phone: switch on location (if using GPS) or tap the map to move yourself. Check the "You are in" fact updates.
7. Phone: change destination, refresh the page (still joined), press Leave. Laptop: phones joined back to 0.
8. Laptop: Restart the event. A phone still joined shows "Lost this person". Press Leave and rejoin. This is expected: a restart creates a fresh crowd.

## 9. The venue editor (draw your own venue)

Open http://localhost:8000/editor.html. You must be signed in as an operator.

1. **Rectangle:** drag two boxes side by side. These are zones.
2. **Gate:** drag along the edge the two boxes share. The zones are found automatically. A gate not on a shared edge gives an error.
3. **Place:** pick a kind (exit, food, toilets, stage, medical, meeting point, assembly point) and click inside a zone. Mark at least one exit or assembly point as safe.
4. Click a zone, gate or place to edit its name, kind, size (gate width in metres drives how many people can pass per second) or limits.
5. **Polygon:** click corners, press Enter to finish. Undo is Ctrl+Z. Scroll to zoom, right-drag to pan. Snap helps align corners.
6. **Levels:** add a floor (for example a grandstand deck) and assign zones to it.
7. **Check** validates the venue. Every zone must be able to reach a safe place.
8. **Save** stores it in `venues/user/`. **Export** downloads the JSON. **Import** loads a JSON file.
9. **Try it** saves, starts an event with the `auto-egress` scenario and opens the control room on it with demo people on.
10. **Real-world position** in the right panel sets the GPS anchor (section 8.3).

## 10. The run viewer (replay and compare)

1. Run a scenario from the command line (section 6). It writes `runs/<scenario>-<planner>.jsonl`. Or tick "Record this event" in the control room.
2. Open http://localhost:8000/viewer.html and load a file from `runs/`.
3. Scrub the timeline and watch the crowd, queues and gates replay. See `test.md` section 6 for what each view shows.

## 11. Testing the server directly (API)

Docs with try-it buttons: http://localhost:8000/docs. Full reference: `docs/api.md`.

```
curl localhost:8000/api/health
curl localhost:8000/api/join/DEMO
```

Sign in and control an event:

```
TOKEN=$(curl -s -X POST localhost:8000/api/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -X POST localhost:8000/api/sessions -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"venue":"example-minimal-festival","scenario":"gate-failure-egress","planner":"adaptive","total":2000,"speed":20,"code":"TEST1"}'

curl -X POST localhost:8000/api/sessions/TEST1/mode -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"mode":"evacuation"}'
curl -X POST localhost:8000/api/sessions/TEST1/closure -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"threshold":"t_field_exit_south","closed":true}'
curl -X DELETE localhost:8000/api/sessions/TEST1 -H "authorization: Bearer $TOKEN"
```

Pretend to be a phone with no browser:

```
curl -X POST localhost:8000/api/join/DEMO/guest -H 'content-type: application/json' -d '{"zone":"main_field","destination":"nearest_safe"}'
# returns person_id and token
curl localhost:8000/api/join/DEMO/guest/PERSON_ID/guidance -H 'X-Guest-Token: TOKEN'
curl -X POST localhost:8000/api/join/DEMO/guest/PERSON_ID/position -H 'X-Guest-Token: TOKEN' -H 'content-type: application/json' -d '{"x":100,"y":60,"accuracy_m":5}'
curl -X POST localhost:8000/api/join/DEMO/guest/PERSON_ID/position -H 'X-Guest-Token: TOKEN' -H 'content-type: application/json' -d '{"lat":-33.8970,"lon":151.2310,"accuracy_m":8}'
```

The `x`,`y` form uses venue metres. The `lat`,`lon` form needs the venue anchor.

## 12. Automated browser tests (optional)

They drive real pages with a headless browser. Needs `npm i -D playwright && npx playwright install chromium` once.

```
E2E_USER=admin E2E_PASS=yourpassword node e2e/live.js
E2E_USER=admin E2E_PASS=yourpassword node e2e/app.js
E2E_USER=admin E2E_PASS=yourpassword node e2e/editor.js
```

Each prints what it checked plus any console errors. `app.js` includes a fake GPS test. They create and stop their own events and save a venue called `e2e-venue`, so use a demo server, not a shared one.

## 13. How to know it is working correctly

- Evacuation clears faster than egress. `adaptive` clears faster than `baseline` in `egress-end-of-night`, `gate-failure-egress` and `dense-dispersal`.
- `arrived_share` is 1.0 and `stuck` is 0 in every scenario.
- Closing the only route to a place makes people "stuck" (that is correct, nothing can reach it).
- Peak density stays near or below about 4 people per square metre. The dense scenario gets closest.
- A phone's instruction always names a gate that is not closed.
- The same seed gives the same numbers every time (the runs are deterministic).

## 14. Known limits (do not report these as bugs)

- Only you are real. Everyone else is simulated, and sensor inputs (cameras, turnstiles) are emulated, not connected to real devices.
- GPS gives no floor. On multi-level venues use tap on the map.
- GPS accuracy is poor between tall buildings and indoors. The app ignores fixes worse than 50 m.
- Guidance is zone and gate level ("go to this gate"), not street-level turn by turn.
- No password reset, single sign-on or audit log.
- Restarting an event drops the phones in it.
- Not safety certified. Do not use it to guide a real evacuation.

## 15. Troubleshooting

| Problem | Fix |
|---|---|
| Pages say "Server not reachable" | Start with `./run.sh`. In dev mode use :5173 |
| Phone cannot open the address | Same Wi-Fi, use the IP not `localhost`, allow incoming connections in the firewall |
| "no event with that code" | Check the code in the control room Events card |
| Location checkbox missing | The venue has no anchor, or the page is not HTTPS or localhost. Tap on the map still works |
| "outside the venue" with GPS | Move the anchor to where you are (section 8.3) or use the DevTools location override |
| Stuck on the login page | Check the password in the terminal output, or delete `data/users.json` and restart |
| Port busy | `PORT=9000 ./run.sh` |
| Page looks stale after an update | Hard refresh. The phone app caches its shell: remove the home screen icon and re-add |
| Tests fail on a fresh checkout | `uv sync --all-packages` and `cd viz && npm install`, then rerun |
