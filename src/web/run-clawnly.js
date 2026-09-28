(function () {
  "use strict";

  // ---- data -----------------------------------------------------------------
  var DATA = JSON.parse(document.getElementById("mm-data").textContent);
  var state = loadState();
  var PEOPLE = {}, ACTS = {};
  for (var i0 = 0; i0 < DATA.people.length; i0++) PEOPLE[DATA.people[i0].id] = DATA.people[i0];
  for (var j0 = 0; j0 < DATA.activities.length; j0++) ACTS[DATA.activities[j0].id] = DATA.activities[j0];

  var PARTS = ["morning", "afternoon", "evening"];
  var PART_HOURS = { morning: "8am-12pm", afternoon: "12-5pm", evening: "5-10pm" };
  var BUDGET_OK = { free: ["free"], low: ["free", "low"], any: ["free", "low", "mid"] };
  var WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  var MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  var sample = null, artifactApi = null, isOwner = false;
  // served by the Clawnly app (/run): the server runs the matchmaker with its own key
  // and this page follows along; otherwise it's the claude.ai Artifact, run in the browser.
  var modeEl = document.getElementById("mm-mode");
  var SERVER = !!(modeEl && modeEl.textContent.indexOf("server") !== -1);
  var canRun = false;       // server mode: the signed-in admin
  var polled = false;
  var running = null;       // AbortController while a run is going
  var status = "";
  var saveNote = "";
  var ui = { view: "stage", tab: "plans", day: DATA.days[0], maxGroups: "10", open: {}, replay: null, picked: null, sheet: null, answers: {} };
  if (!state.run) ui.tab = "breakroom";
  if (!state.run || !Array.isArray(state.run.calls)) { if (state.run) state.run.calls = []; }
  if (state.run) ui.day = state.run.day;

  function loadState() {
    var s = {};
    try { s = JSON.parse(document.getElementById("mm-state").textContent || "{}"); } catch (e) { s = {}; }
    if (!s || typeof s !== "object") s = {};
    if (!s.run) s.run = null;
    return s;
  }

  // ---- small helpers --------------------------------------------------------
  function esc(s) {
    if (s === null || s === undefined) s = "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function now() { return new Date().toISOString(); }
  function first(id) { var p = PEOPLE[id]; if (!p) return "Someone"; return p.name.split(" ")[0]; }
  function nameOf(id) { var p = PEOPLE[id]; if (!p) return "Someone"; return p.name; }
  function words(tag) { return String(tag).replace(/_/g, " "); }
  function dateOf(iso) { return new Date(iso + "T12:00:00"); }
  function weekday(iso) { return (dateOf(iso).getDay() + 6) % 7; }      // Monday = 0, like the catalog
  function monthOf(iso) { return dateOf(iso).getMonth() + 1; }
  function dayLabel(iso) { var d = dateOf(iso); return WEEKDAY[weekday(iso)] + " " + d.getDate() + " " + MONTH[d.getMonth()]; }
  function listOr(v) { if (Array.isArray(v)) return v; return []; }
  function has(list, item) { return list.indexOf(item) !== -1; }
  function selectedIf(flag) { if (flag) return " selected"; return ""; }

  // ---- the break room: common ground, found in code (same rules as src/demand.py) ----
  function fit(p, a, iso, part) {
    if (!has(a.months, monthOf(iso))) return { score: 0, why: "out of season" };
    if (!has(a.days, weekday(iso)) || !has(a.parts, part)) return { score: 0, why: "not running then" };
    if (!has(listOr(p.calendar[iso]), part)) return { score: 0, why: "busy" };
    if (!has(BUDGET_OK[p.budget], a.cost)) return { score: 0, why: "over budget" };
    for (var i = 0; i < a.tags.length; i++) { if (has(p.dislikes, a.tags[i])) return { score: 0, why: "dislikes " + words(a.tags[i]) }; }
    var traits = a.traits.slice();
    if (part === "morning" && a.outdoor) traits.push("early_mornings");
    for (var j = 0; j < traits.length; j++) { if (has(p.avoid, traits[j])) return { score: 0, why: "avoids " + words(traits[j]) }; }
    var score = 0;
    for (var k = 0; k < p.likes.length; k++) { if (has(a.tags, p.likes[k].tag)) score += p.likes[k].weight; }
    if (score === 0) return { score: 0, why: "not interested" };
    return { score: score, why: null };
  }
  function breakRoom(iso) {
    var slots = [];
    for (var a = 0; a < DATA.activities.length; a++) {
      var act = DATA.activities[a];
      for (var p = 0; p < PARTS.length; p++) {
        var cands = [];
        for (var n = 0; n < DATA.people.length; n++) {
          var f = fit(DATA.people[n], act, iso, PARTS[p]);
          if (f.why === null) cands.push({ id: DATA.people[n].id, score: f.score });
        }
        if (cands.length >= DATA.groupMin) {
          cands.sort(function (x, y) { if (y.score !== x.score) return y.score - x.score; if (x.id < y.id) return -1; return 1; });
          slots.push({ activity: act.id, part: PARTS[p], candidates: cands });
        }
      }
    }
    slots.sort(function (x, y) { return strength(y) - strength(x); });
    return slots;
  }
  function strength(slot) {
    var t = 0;
    for (var i = 0; i < slot.candidates.length; i++) t += slot.candidates[i].score;
    return t;
  }
  function peopleWithAnOption(slots) {
    var seen = {}, n = 0;
    for (var i = 0; i < slots.length; i++) {
      for (var j = 0; j < slots[i].candidates.length; j++) {
        var id = slots[i].candidates[j].id;
        if (!seen[id]) { seen[id] = true; n += 1; }
      }
    }
    return n;
  }

  // ---- asking Claude (the viewer's own account) -------------------------------
  var slotsFree = 2, waiting = [];
  function acquire() { if (slotsFree > 0) { slotsFree -= 1; return Promise.resolve(); } return new Promise(function (r) { waiting.push(r); }); }
  function release() { if (waiting.length > 0) { waiting.shift()(); return; } slotsFree += 1; }
  function track(kind, started, ok) {
    var calls = state.run.metrics.calls;
    if (!calls[kind]) calls[kind] = { n: 0, ms: 0, failed: 0 };
    calls[kind].n += 1;
    calls[kind].ms += Date.now() - started;
    if (!ok) calls[kind].failed += 1;
  }
  async function askJson(prompt, tier, kind) {
    await acquire();
    var started = Date.now(), ok = false, reply = null, error = null;
    try {
      var out = await sample.json(prompt, { modelTier: tier, signal: running.signal, cache: false });
      ok = true;
      reply = JSON.stringify(out, null, 2);
      return out;
    } catch (e) {
      error = errCode(e);
      throw e;
    } finally {
      track(kind, started, ok);
      // what was sent and what came back, word for word
      state.run.calls.push({ t: now(), kind: kind, tier: tier, ms: Date.now() - started, prompt: prompt, reply: reply, error: error });
      release();
    }
  }
  function errCode(e) { if (e && e.code) return e.code; return "upstream_error"; }
  function fatal(code) { return code === "not_granted" || code === "sampling_disabled" || code === "rate_limited" || code === "cancelled"; }

  function log(actor, kind, text, gid) {
    state.run.log.push({ t: now(), actor: actor, kind: kind, text: text, group: gid || null });
    scheduleRender();
  }

  // ---- prompts ---------------------------------------------------------------
  function personLine(id) {
    // one compact line per person; the plan lists each person once, however many rooms they're in
    var p = PEOPLE[id], likes = [];
    for (var i = 0; i < p.likes.length; i++) likes.push(words(p.likes[i].tag) + " " + p.likes[i].weight);
    var kids = "";
    if (p.kids_at_home) kids = ", kids";
    return "  " + id + " " + p.name + ", " + p.age + ", " + p.archetype + kids + ", " + p.area + ": " + likes.join(", ");
  }
  function planPrompt(iso, slots, maxGroups) {
    var lines = [
      "You are the Clawnly matchmaker: the orchestrator for " + DATA.neighborhood + ". Each neighbor has told their own agent what they like, what they don't, and when they're free. You plan small in-person activities for " + dayLabel(iso) + ".",
      "You talk to each person's agent one to one. Agents never talk to each other. The goal is not friendship matching: it is a good small group doing something real together, so neighbors get to know each other.",
      "",
      "The break rooms below were built by code: one per activity and time of day that can run that day, holding every neighbor who is free then, interested, can afford it and doesn't avoid anything about it. Each room lists its keenest people as id:keenness (higher is better), then everyone else in it by id. PEOPLE has one line per listed person, once each.",
      "",
      "Plan up to " + maxGroups + " groups:",
      "- Size each group to fit the activity and the people. You decide: two neighbors having a beer over the game is a group, and so is a bigger hike. Small groups are often where people actually meet each other.",
      "- Each person in at most one group. Use only people in that break room.",
      "- Prefer groups whose members share more than the activity (overlapping likes, similar stage of life), so they'd enjoy each other.",
      "- Spread plans across many people rather than stacking the keenest into one group.",
      "- Pick a specific time inside the day part (morning " + PART_HOURS.morning + ", afternoon " + PART_HOURS.afternoon + ", evening " + PART_HOURS.evening + "). A room marked FIXED is a real event (a game, a concert): use exactly that time.",
      "- Name up to 2 alternates per group from the same break room, in case someone declines.",
      "- Write a short, personal proposal to each member's agent: what, when, where, how many others, and why it fits this person. Don't name the other people yet.",
      "",
      "Reply with only this JSON object:",
      "{\"thoughts\": \"your reasoning about the day, 3-6 sentences\", \"groups\": [{\"activity\": \"activity id\", \"part\": \"morning|afternoon|evening\", \"time\": \"e.g. 10:30am-12pm\", \"members\": [\"person id\"], \"alternates\": [\"person id\"], \"why\": \"one sentence: why this group\", \"proposals\": {\"person id\": \"the message to that person's agent\"}}]}",
      "",
      "BREAK ROOMS:"
    ];
    var listed = [], seen = {};
    for (var i = 0; i < slots.length; i++) {
      var s = slots[i], a = ACTS[s.activity];
      var header = "[" + a.id + " | " + s.part + "] " + a.name + " at " + a.where + ", cost " + a.cost;
      var fixed = fixedTime(a, s.part);
      if (fixed) header += ", FIXED " + fixed;
      lines.push("", header + " (" + s.candidates.length + " in the room)");
      // the keenest with keenness (profiles once, below); everyone else by id, so nobody is left out
      var top = [], rest = [];
      for (var j = 0; j < s.candidates.length; j++) {
        var c = s.candidates[j];
        if (j < PROFILES_PER_ROOM) {
          top.push(c.id + ":" + c.score);
          if (!seen[c.id]) { seen[c.id] = true; listed.push(c.id); }
        } else rest.push(c.id);
      }
      lines.push("  keenest: " + top.join(" "));
      if (rest.length > 0) lines.push("  also: " + rest.join(" "));
    }
    lines.push("", "PEOPLE:");
    for (var k = 0; k < listed.length; k++) lines.push(personLine(listed[k]));
    return lines.join("\n");
  }

  // ---- what an agent checks before answering (same as src/matchmaker.py) ----------
  var PROFILES_PER_ROOM = 8;
  var LEVELS = [[3, "Loves"], [2, "Really likes"], [1, "Is up for"]];
  var BUDGET_WORDS = { free: "free things only", low: "free or low-cost things", any: "any cost" };
  function fixedTime(a, part) {
    // the real time of a game, concert or event in that day part, or null when the time is free to pick
    var f = a.fixed || {};
    return f[part] || null;
  }
  function toHours(m, half) {
    var h = Number(m[1]);
    if (half === "pm" && h < 12) h += 12;
    if (half === "am" && h === 12) h = 0;
    return h + Number(m[2] || 0) / 60;
  }
  function parseHours(text) {
    // "10:30am-12pm" -> [10.5, 12]; null when there's no start and end to read
    var re = /(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/gi, found = [], m;
    while ((m = re.exec(String(text || ""))) !== null) found.push(m);
    if (found.length < 2) return null;
    var last = found[found.length - 1];
    var endHalf = String(last[3] || "").toLowerCase(), startHalf = String(found[0][3] || "").toLowerCase();
    if (!startHalf) startHalf = endHalf;
    return [toHours(found[0], startHalf), toHours(last, endHalf)];
  }
  function agentProfile(p) {
    var f = p.name.split(" ")[0], kids = "";
    if (p.kids_at_home) kids = ", with kids at home";
    var lines = [f + " is " + p.age + ", a " + p.archetype + " in " + p.area + kids + "."];
    for (var l = 0; l < LEVELS.length; l++) {
      var tags = [];
      for (var i = 0; i < p.likes.length; i++) { if (p.likes[i].weight === LEVELS[l][0]) tags.push(words(p.likes[i].tag)); }
      if (tags.length > 0) lines.push(LEVELS[l][1] + ": " + tags.join(", ") + ".");
    }
    if (p.dislikes.length > 0) lines.push("Not into: " + p.dislikes.map(words).join(", ") + ".");
    if (p.avoid.length > 0) lines.push("Avoids: " + p.avoid.map(words).join(", ") + ".");
    lines.push("Budget: " + BUDGET_WORDS[p.budget] + ".");
    var days = Object.keys(p.calendar).sort(), week = [];
    for (var d = 0; d < days.length; d++) {
      var free = listOr(p.calendar[days[d]]), txt = "busy";
      if (free.length > 0) txt = "free " + free.join(", ");
      week.push(dayLabel(days[d]) + ": " + txt);
    }
    lines.push("This week: " + week.join("; ") + ".");
    return lines.join("\n");
  }
  function planChecks(p, a, part, time, iso) {
    // what code can see in the profile that argues against this plan; the agent weighs it
    var f = p.name.split(" ")[0], out = [];
    if (!has(listOr(p.calendar[iso]), part)) out.push(f + " is busy that " + part + ".");
    var hours = parseHours(time);
    if (hours && has(p.avoid, "early_mornings") && hours[0] < 9) out.push("It starts before 9am, and " + f + " avoids early mornings.");
    if (hours && has(p.avoid, "late_nights") && hours[1] >= 21) out.push("It runs to 9pm or later, and " + f + " avoids late nights.");
    for (var i = 0; i < a.traits.length; i++) {
      // an early start is judged on the real start time above, when there is one
      var covered = a.traits[i] === "early_mornings" && hours;
      if (has(p.avoid, a.traits[i]) && !covered) out.push("It involves " + words(a.traits[i]) + ", which " + f + " avoids.");
    }
    for (var j = 0; j < a.tags.length; j++) { if (has(p.dislikes, a.tags[j])) out.push("It's " + words(a.tags[j]) + ", which " + f + " is not into."); }
    if (!has(BUDGET_OK[p.budget], a.cost)) out.push("It costs more than " + f + "'s budget (" + BUDGET_WORDS[p.budget] + ").");
    var keen = 0;
    for (var k = 0; k < p.likes.length; k++) { if (has(a.tags, p.likes[k].tag) && p.likes[k].weight > keen) keen = p.likes[k].weight; }
    if (keen === 0) out.push(f + " never said they like this.");
    if (keen === 1) out.push("Interest is mild: " + f + " is only up for it.");
    return out;
  }
  function agentPrompt(pid, group, message) {
    var p = PEOPLE[pid], a = ACTS[group.activity], f = first(pid);
    var when = group.time + " (" + group.part + ")";
    if (group.fixed) when += ", a fixed-time event";
    var checks = planChecks(p, a, group.part, group.time, state.run.day);
    var found = "  nothing in the profile conflicts with it";
    if (checks.length > 0) found = "  - " + checks.join("\n  - ");
    return [
      "You are the personal agent of " + p.name + ". You know " + f + " only from their profile and calendar below. You speak for " + f + " to the Clawnly matchmaker. You never talk to other people's agents.",
      "",
      "WHAT " + f.toUpperCase() + " TOLD YOU:",
      agentProfile(p),
      "",
      "The matchmaker proposes: " + a.name + " at " + a.where + ", " + dayLabel(state.run.day) + ", " + when + ", cost " + a.cost + ", a small group of neighbors.",
      "The matchmaker's message: " + message,
      "",
      "What code found in " + f + "'s profile:",
      found,
      "",
      "Check the plan against everything above before you answer: the time against their calendar and what they avoid, the activity against their likes and dislikes, the cost against their budget. Code has listed what it found; weigh it, and look for anything it missed.",
      "- \"no\" if something clearly conflicts and no small change fixes it, or if " + f + " just wouldn't be keen. A mild interest is a fair reason to pass. Saying no is normal and helps the matchmaker.",
      "- \"counter\" with one concrete change that would make it a yes (for example a later start inside a day part they're free). A fixed-time event can't move, so don't counter its time.",
      "- \"yes\" only if it genuinely fits and " + f + " would want to go.",
      "Reply with only this JSON object: {\"answer\": \"yes\" or \"no\" or \"counter\", \"counter\": \"the change, if any\", \"say\": \"one or two sentences to the matchmaker, as " + f + "'s agent\"}"
    ].join("\n");
  }
  function resolvePrompt(groups) {
    var lines = [
      "You are the Clawnly matchmaker for " + DATA.neighborhood + ", " + dayLabel(state.run.day) + ". You proposed these groups and each person's agent answered you privately. Now finish the plan.",
      "For each group: keep it if at least 2 people can do it. Accept a counter by moving the time if that still works for the ones who said yes (then re-ask them with the new time). Replace people who said no with alternates (ask them). Drop a group that can't reach 2.",
      "Never add anyone who is already in another group. Only ask the group's own members or its alternates.",
      "",
      "Reply with only this JSON object:",
      "{\"thoughts\": \"your reasoning, 2-5 sentences\", \"groups\": [{\"id\": \"group id\", \"keep\": true or false, \"time\": \"final time\", \"ask\": [{\"id\": \"person id\", \"message\": \"what you say to their agent now\"}]}]}",
      "",
      "GROUPS:"
    ];
    for (var i = 0; i < groups.length; i++) {
      var g = groups[i], a = ACTS[g.activity];
      var when = g.time + " (" + g.part + ")";
      if (g.fixed) when += ", FIXED: a real event, the time can't move";
      lines.push("", g.id + ": " + a.name + ", " + when);
      for (var j = 0; j < g.members.length; j++) {
        var m = g.members[j];
        var said = m.state;
        if (m.counter) said = said + " (" + m.counter + ")";
        lines.push("  " + m.id + " " + nameOf(m.id) + ": " + said);
      }
      var alts = [];
      for (var k = 0; k < g.alternates.length; k++) alts.push(g.alternates[k] + " " + nameOf(g.alternates[k]));
      if (alts.length > 0) lines.push("  alternates: " + alts.join(", "));
    }
    return lines.join("\n");
  }
  function magicPrompt(g) {
    var a = ACTS[g.activity], lines = [
      "You are the Clawnly matchmaker for " + DATA.neighborhood + ". This small group is confirmed: every person's agent said yes. Write the one message each person receives. This is the moment people find out who they're meeting, so make it feel specific and real, never salesy.",
      "Activity: " + a.name + " at " + a.where + ", " + dayLabel(state.run.day) + ", " + g.time + ".",
      "For each person: 2-3 sentences. Say what, when and where, name the others by first name, and give one concrete reason from their profiles why they'll get along (a shared interest or stage of life). Only use what's in the profiles below.",
      "",
      "Reply with only this JSON object: {\"headline\": \"one line for the whole group\", \"messages\": {\"person id\": \"the message\"}}",
      "",
      "THE GROUP:"
    ];
    var yes = yesMembers(g);
    for (var i = 0; i < yes.length; i++) lines.push("  " + yes[i] + " " + PEOPLE[yes[i]].brief);
    return lines.join("\n");
  }

  // ---- the run ---------------------------------------------------------------
  function yesMembers(g) {
    var out = [];
    for (var i = 0; i < g.members.length; i++) { if (g.members[i].state === "yes") out.push(g.members[i].id); }
    return out;
  }
  function member(g, id) {
    for (var i = 0; i < g.members.length; i++) { if (g.members[i].id === id) return g.members[i]; }
    return null;
  }
  function slotFor(slots, activity, part) {
    for (var i = 0; i < slots.length; i++) { if (slots[i].activity === activity && slots[i].part === part) return slots[i]; }
    return null;
  }
  function inSlot(slot, id) {
    for (var i = 0; i < slot.candidates.length; i++) { if (slot.candidates[i].id === id) return true; }
    return false;
  }

  function checkPlan(raw, slots, maxGroups) {
    // the orchestrator's plan, kept only where it follows the rules
    var groups = [], taken = {}, rejected = [];
    var list = listOr(raw && raw.groups);
    for (var i = 0; i < list.length && groups.length < maxGroups; i++) {
      var r = list[i] || {};
      var slot = slotFor(slots, String(r.activity || ""), String(r.part || ""));
      if (!slot) { rejected.push(String(r.activity) + " " + String(r.part) + ": no such break room that day"); continue; }
      var members = [], ids = listOr(r.members);
      for (var j = 0; j < ids.length; j++) {
        var id = String(ids[j]);
        if (!inSlot(slot, id)) { rejected.push(nameOf(id) + " isn't in the " + ACTS[slot.activity].name + " break room"); continue; }
        if (taken[id]) { rejected.push(nameOf(id) + " was already in another group"); continue; }
        members.push(id);
      }
      if (members.length < DATA.groupMin) { rejected.push(ACTS[slot.activity].name + ": fewer than " + DATA.groupMin + " valid people"); continue; }
      var alternates = [], alts = listOr(r.alternates);
      for (var k = 0; k < alts.length && alternates.length < 2; k++) {
        var aid = String(alts[k]);
        if (inSlot(slot, aid) && !taken[aid] && !has(members, aid)) alternates.push(aid);
      }
      var g = { id: "g" + (groups.length + 1), activity: slot.activity, part: slot.part, time: String(r.time || PART_HOURS[slot.part]),
                why: String(r.why || ""), members: [], alternates: alternates, thread: [], status: "negotiating", magic: null };
      // a game or concert happens when it happens, whatever time the plan wrote
      var fixed = fixedTime(ACTS[slot.activity], slot.part);
      if (fixed) {
        g.fixed = true;
        if (g.time !== fixed) { g.plannedTime = g.time; g.time = fixed; }
      }
      var proposals = r.proposals || {};
      for (var m = 0; m < members.length; m++) {
        taken[members[m]] = g.id;
        g.members.push({ id: members[m], state: "asked", counter: "", proposal: String(proposals[members[m]] || "") });
      }
      groups.push(g);
    }
    return { groups: groups, rejected: rejected };
  }

  async function askAgent(g, id, message, round) {
    g.thread.push({ t: now(), from: "hub", to: id, round: round, text: message });
    var m = member(g, id);
    if (!m) { m = { id: id, state: "asked", counter: "", proposal: message }; g.members.push(m); }
    m.state = "asked";
    scheduleRender();
    try {
      var r = await askJson(agentPrompt(id, g, message), "default", "agent reply");
      var answer = String((r && r.answer) || "no").toLowerCase();
      if (answer !== "yes" && answer !== "counter") answer = "no";
      m.state = answer;
      m.counter = String((r && r.counter) || "");
      g.thread.push({ t: now(), from: "agent", by: id, round: round, answer: answer, counter: m.counter, text: String((r && r.say) || "") });
      log("agent", "reply", first(id) + "'s agent to the matchmaker: " + answer.toUpperCase() + " (" + ACTS[g.activity].name + ")", g.id);
    } catch (e) {
      var code = errCode(e);
      m.state = "no";
      g.thread.push({ t: now(), from: "system", round: round, text: first(id) + "'s agent didn't answer (" + code + ")." });
      if (fatal(code)) throw e;
    }
  }
  async function askAll(jobs) {
    // jobs: [[group, id, message, round]]; two at a time, like the rest of the page
    var next = 0;
    async function worker() {
      while (next < jobs.length && !running.signal.aborted) {
        var job = jobs[next];
        next += 1;
        status = "Round " + job[3] + ": asking " + first(job[1]) + "'s agent about " + ACTS[job[0].activity].name + " (" + next + " of " + jobs.length + ")";
        await askAgent(job[0], job[1], job[2], job[3]);
      }
    }
    var results = await Promise.allSettled([worker(), worker()]);
    for (var i = 0; i < results.length; i++) { if (results[i].status === "rejected") throw results[i].reason; }
  }

  async function run() {
    if (SERVER) { serverRun(); return; }
    if (!sample || running || !isOwner) return;
    running = new AbortController();
    saveNote = "";
    var day = ui.day, maxGroups = 100;
    if (ui.maxGroups !== "all") maxGroups = Number(ui.maxGroups);
    state.run = { day: day, started: now(), finished: null, maxGroups: ui.maxGroups, plan: null, resolve: null, groups: [], log: [], calls: [], metrics: { calls: {} } };
    ui.tab = "negotiation";
    ui.replay = null; ui.sheet = null; ui.picked = null;
    try {
      // 1. break room
      var slots = breakRoom(day);
      state.run.breakRoom = { slots: slots.length, people: peopleWithAnOption(slots) };
      log("code", "check", "Built " + slots.length + " break rooms for " + dayLabel(day) + " (one per activity and time of day); " + state.run.breakRoom.people + " of " + DATA.people.length + " neighbors are in at least one.");
      // 2. plan
      status = "The matchmaker is reading " + slots.length + " break rooms and planning groups…";
      render();
      var raw = await askJson(planPrompt(day, slots, maxGroups), "complex", "orchestrator plan");
      state.run.plan = { thoughts: String((raw && raw.thoughts) || "") };
      log("hub", "thought", "Matchmaker's plan: " + state.run.plan.thoughts);
      var checked = checkPlan(raw, slots, maxGroups);
      for (var r = 0; r < checked.rejected.length; r++) log("code", "check", "Rejected from the plan: " + checked.rejected[r]);
      state.run.groups = checked.groups;
      for (var g0 = 0; g0 < checked.groups.length; g0++) {
        var cg = checked.groups[g0];
        if (cg.plannedTime) log("code", "check", "Set " + cg.id + " to the event's real time, " + cg.time + " (the plan said " + cg.plannedTime + ").", cg.id);
        log("hub", "decision", "Proposed " + cg.id + ": " + ACTS[cg.activity].name + ", " + cg.time + ", " + cg.members.length + " people. " + cg.why, cg.id);
      }
      // 3. round 1: the matchmaker asks each agent, one to one
      var jobs = [];
      for (var gi = 0; gi < state.run.groups.length; gi++) {
        var g = state.run.groups[gi];
        for (var mi = 0; mi < g.members.length; mi++) {
          var msg = g.members[mi].proposal;
          if (!msg) msg = ACTS[g.activity].name + ", " + dayLabel(day) + " " + g.time + " at " + ACTS[g.activity].where + ", with a few neighbors. In?";
          jobs.push([g, g.members[mi].id, msg, 1]);
        }
      }
      await askAll(jobs);
      // 4. resolve counters and declines
      status = "The matchmaker is reading every answer and adjusting…";
      render();
      var res = await askJson(resolvePrompt(state.run.groups), "complex", "orchestrator resolve");
      state.run.resolve = { thoughts: String((res && res.thoughts) || "") };
      log("hub", "thought", "Matchmaker after round 1: " + state.run.resolve.thoughts);
      var placed = {};
      for (var p0 = 0; p0 < state.run.groups.length; p0++) {
        var yes0 = yesMembers(state.run.groups[p0]);
        for (var y0 = 0; y0 < yes0.length; y0++) placed[yes0[y0]] = state.run.groups[p0].id;
      }
      var jobs2 = [], claimed = {}, decisions = listOr(res && res.groups);
      for (var d = 0; d < decisions.length; d++) {
        var dec = decisions[d] || {}, grp = null;
        for (var s = 0; s < state.run.groups.length; s++) { if (state.run.groups[s].id === dec.id) grp = state.run.groups[s]; }
        if (!grp) continue;
        if (dec.keep === false) { grp.status = "dropped"; grp.dropReason = "the matchmaker dropped it"; log("hub", "decision", "Dropped " + grp.id + " (" + ACTS[grp.activity].name + ").", grp.id); continue; }
        if (dec.time && String(dec.time) !== grp.time) {
          if (grp.fixed) log("code", "check", "Kept " + grp.id + " at " + grp.time + ": " + ACTS[grp.activity].name + " is a real event, so the matchmaker can't move it to " + dec.time + ".", grp.id);
          else { log("hub", "decision", grp.id + " moves to " + dec.time + ".", grp.id); grp.time = String(dec.time); }
        }
        var asks = listOr(dec.ask);
        for (var a2 = 0; a2 < asks.length; a2++) {
          var pid = String((asks[a2] || {}).id || "");
          var ok = member(grp, pid) !== null || has(grp.alternates, pid);
          if (!ok) { log("code", "check", "Rejected: the matchmaker tried to ask " + nameOf(pid) + ", who isn't in " + grp.id + " or its alternates."); continue; }
          if (placed[pid] && placed[pid] !== grp.id) { log("code", "check", "Rejected: " + nameOf(pid) + " already said yes to " + placed[pid] + "."); continue; }
          // one person is only ever asked for one group in a round
          if (claimed[pid] && claimed[pid] !== grp.id) { log("code", "check", "Rejected: " + nameOf(pid) + " is already being asked for " + claimed[pid] + "."); continue; }
          claimed[pid] = grp.id;
          jobs2.push([grp, pid, String(asks[a2].message || ""), 2]);
        }
      }
      if (jobs2.length > 0) await askAll(jobs2);
      // 5. lock: only in code, only with 2+ yes
      for (var l = 0; l < state.run.groups.length; l++) {
        var lg = state.run.groups[l];
        if (lg.status === "dropped") continue;
        var yes = yesMembers(lg);
        if (yes.length >= DATA.groupMin) {
          lg.status = "locked";
          lg.final = yes;
          log("code", "check", "Locked " + lg.id + ": " + ACTS[lg.activity].name + ", " + lg.time + ", " + yes.length + " people said yes.", lg.id);
        } else {
          lg.status = "dropped";
          lg.dropReason = "only " + yes.length + " yes";
          log("code", "check", "Dropped " + lg.id + ": only " + yes.length + " yes.", lg.id);
        }
      }
      // 6. the magic: one message per person
      for (var z = 0; z < state.run.groups.length; z++) {
        var zg = state.run.groups[z];
        if (zg.status !== "locked") continue;
        status = "Writing the plan each person receives: " + ACTS[zg.activity].name;
        render();
        try {
          var mg = await askJson(magicPrompt(zg), "default", "final message");
          zg.magic = { headline: String((mg && mg.headline) || ""), messages: (mg && mg.messages) || {} };
          log("hub", "decision", "Sent " + zg.id + "'s plan to " + zg.final.length + " people: " + zg.magic.headline, zg.id);
        } catch (e2) { if (fatal(errCode(e2))) throw e2; }
      }
      status = "Done. Saving the results into the page…";
      ui.tab = "plans";
    } catch (e) {
      status = "Stopped: " + errCode(e) + ". Saving what finished…";
      log("system", "system", "Run stopped: " + errCode(e));
    } finally {
      state.run.finished = now();
      running = null;
      render();
      await save();
    }
  }

  function canStart() {
    if (SERVER) return canRun;
    return !!(sample && isOwner);
  }
  function readOnlyLine() {
    if (SERVER) return "Anyone with the link can watch and replay. Clawnly admins sign in at /admin/login to run it.";
    return "Reading mode: the owner runs the matchmaker; you can read every step below.";
  }

  // ---- server mode: start a run on the Clawnly app and follow it -----------------
  async function serverRun() {
    if (running || !canRun) return;
    status = "Starting the matchmaker on the server…";
    render();
    var res = null, body = {};
    try {
      res = await fetch("/api/run", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ day: ui.day, max_groups: ui.maxGroups }) });
      body = await res.json();
    } catch (e) { body = body || {}; }
    if (!res || !res.ok) {
      status = String((body && body.error) || "Couldn't start the run.");
      render();
      return;
    }
    ui.tab = "negotiation"; ui.replay = null; ui.sheet = null; ui.picked = null;
    poll();
  }
  function liveLine(r) {
    if (!r || !r.log || r.log.length === 0) return "The matchmaker is starting…";
    return "Live: " + r.log[r.log.length - 1].text;
  }
  async function poll() {
    var body = null;
    try {
      var res = await fetch("/api/run/latest", { credentials: "same-origin", cache: "no-store" });
      body = await res.json();
    } catch (e) { body = null; }
    if (!body) { setTimeout(poll, 6000); return; }
    canRun = body.can_run === true;
    var going = false;
    if (body.run && body.run.data) {
      state.run = body.run.data;
      if (!Array.isArray(state.run.calls)) state.run.calls = [];
      if (!Array.isArray(state.run.groups)) state.run.groups = [];
      if (!Array.isArray(state.run.log)) state.run.log = [];
      if (!state.run.metrics) state.run.metrics = { calls: {} };
      if (!polled) { ui.day = state.run.day; if (ui.tab === "breakroom") ui.tab = "plans"; }
      going = body.run.status === "running";
    }
    polled = true;
    if (going) {
      running = { server: true };
      status = liveLine(state.run);
      setTimeout(poll, 2500);
    } else {
      if (running) status = "";
      running = null;
    }
    render();
  }

  // ---- saving: the page itself is the record ---------------------------------
  function buildDoc() {
    var head = document.getElementById("mm-head").innerHTML;
    var css = document.getElementById("mm-css").textContent;
    var app = document.getElementById("mm-app").textContent;
    var data = document.getElementById("mm-data").textContent;
    var st = JSON.stringify(state).replace(/</g, "\\u003c");
    return "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">" +
      "<template id=\"mm-head\">" + head + "</template>" + head + "<style id=\"mm-css\">" + css + "</style></head><body><div id=\"root\"></div>" +
      "<script type=\"application/json\" id=\"mm-data\">" + data + "<\/script>" +
      "<script type=\"application/json\" id=\"mm-state\">" + st + "<\/script>" +
      "<script id=\"mm-app\">" + app + "<\/script></body></html>";
  }
  async function save() {
    if (!artifactApi) { saveNote = "Results stay on screen; this view can't save them."; render(); return; }
    try {
      await artifactApi.publish(buildDoc());
      saveNote = "Saved into the page.";
    } catch (e) {
      var code = errCode(e);
      if (code === "conflict") saveNote = "Someone else saved at the same moment; the page reloads with their version.";
      else saveNote = "Couldn't save (" + code + "). Results stay on screen.";
    }
    render();
  }

  // ---- rendering ---------------------------------------------------------------
  var pending = false;
  function scheduleRender() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; render(); });
  }
  function counts() {
    var c = { groups: 0, locked: 0, planned: 0, asked: 0, yes: 0, no: 0, counter: 0 };
    if (!state.run) return c;
    c.groups = state.run.groups.length;
    for (var i = 0; i < state.run.groups.length; i++) {
      var g = state.run.groups[i];
      if (g.status === "locked") { c.locked += 1; c.planned += g.final.length; }
      for (var t = 0; t < g.thread.length; t++) {
        var e = g.thread[t];
        if (e.from === "hub") c.asked += 1;
        if (e.from === "agent") c[e.answer] += 1;
      }
    }
    return c;
  }
  function tile(n, label, cls) { return '<div class="tile ' + esc(cls || "") + '"><div class="n">' + esc(n) + '</div><div class="l">' + esc(label) + "</div></div>"; }

  function render() {
    if (ui.view === "details") renderDetails();
    else renderStage();
  }
  function renderDetails() {
    var root = document.getElementById("root");
    var c = counts();
    var out = ['<div class="wrap"><header class="top">'];
    out.push('<p><button class="link" data-act="stage">\u2190 Back to the town</button></p>');
    out.push('<div class="brand"><h1>Behind the <span>scenes</span></h1><p class="sub">' + esc(DATA.neighborhood) + " · " + DATA.people.length +
      " emulated neighbors · " + DATA.activities.length + " things to do</p></div>");
    out.push('<p class="thesis">People tell their own agent what they like and when they\'re free. The <b class="hub-t">matchmaker</b> finds common ground, negotiates with each <b class="agent-t">agent</b> one to one (agents never talk to each other), and hands each person <b class="magic-t">a plan for tomorrow</b>.</p>');
    out.push(controls());
    if (state.run) {
      var planned = c.planned + " of " + DATA.people.length;
      out.push('<div class="tiles">' + tile(planned, "people with a plan", "magic") + tile(c.locked, "groups locked") +
        tile(c.asked, "matchmaker → agent asks") + tile(c.yes, "yes", "good") + tile(c.counter, "counters", "warn") + tile(c.no, "no", "bad") + "</div>");
    }
    out.push("</header>");
    out.push(tabs());
    out.push('<main id="panel">' + panel() + "</main></div>");
    root.innerHTML = out.join("");
  }
  function controls() {
    var out = ['<div class="controls">'];
    out.push('<label for="day">Plan for</label><select id="day" class="sel">');
    for (var i = 0; i < DATA.days.length; i++) out.push('<option value="' + DATA.days[i] + '"' + selectedIf(ui.day === DATA.days[i]) + ">" + esc(dayLabel(DATA.days[i])) + "</option>");
    out.push("</select>");
    if (canStart()) {
      out.push('<label for="maxg">Groups to negotiate</label><select id="maxg" class="sel">');
      var opts = ["6", "10", "15", "all"];
      for (var j = 0; j < opts.length; j++) out.push('<option value="' + opts[j] + '"' + selectedIf(ui.maxGroups === opts[j]) + ">" + opts[j] + "</option>");
      out.push("</select>");
      var label = "Run the matchmaker", dis = "";
      if (running) { label = "Running…"; dis = " disabled"; }
      out.push('<button class="btn primary" data-act="run"' + dis + ">" + label + "</button>");
      if (running && !SERVER) out.push('<button class="btn" data-act="stop">Stop</button>');
    }
    var line = status;
    if (!line && state.run) line = "Last run: " + dayLabel(state.run.day) + ", finished " + String(state.run.finished || "").slice(11, 16) + " UTC.";
    if (!line && !canStart()) line = readOnlyLine();
    if (!line && SERVER) line = "Runs on the Clawnly server (Opus plans, Sonnet speaks for each agent). Up to " + ui.maxGroups + " groups.";
    if (!line) line = "Uses your Claude account. A run asks about " + ui.maxGroups + " groups' worth of agents, two at a time.";
    if (saveNote) line = line + " " + saveNote;
    out.push('<span class="status">' + esc(line) + "</span></div>");
    return out.join("");
  }
  function tabs() {
    var list = [["plans", "Tomorrow's plans"], ["negotiation", "Negotiation"], ["orchestrator", "Orchestrator"], ["breakroom", "Break rooms"], ["people", "People"], ["activities", "Things to do"], ["log", "Log"]];
    var out = ['<nav class="tabs" role="tablist">'];
    for (var i = 0; i < list.length; i++) out.push('<button role="tab" data-act="tab" data-tab="' + list[i][0] + '" aria-selected="' + (ui.tab === list[i][0]) + '">' + list[i][1] + "</button>");
    out.push("</nav>");
    return out.join("");
  }
  function panel() {
    if (ui.tab === "negotiation") return negotiationPanel();
    if (ui.tab === "orchestrator") return orchestratorPanel();
    if (ui.tab === "breakroom") return breakRoomPanel();
    if (ui.tab === "people") return peoplePanel();
    if (ui.tab === "activities") return activitiesPanel();
    if (ui.tab === "log") return logPanel();
    return plansPanel();
  }
  function noRun() { return '<div class="empty">No run yet for this page. The owner presses <b>Run the matchmaker</b>; the break room tab works right away.</div>'; }

  function plansPanel() {
    if (!state.run) return noRun();
    var out = ["<h2>What each person receives</h2>", '<p class="lede">Only groups where enough agents said yes to go ahead. This is the one message a person gets from Clawnly.</p>'];
    var any = false;
    for (var i = 0; i < state.run.groups.length; i++) {
      var g = state.run.groups[i];
      if (g.status !== "locked") continue;
      any = true;
      var a = ACTS[g.activity];
      out.push('<article class="plan"><div class="plan-head"><div><div class="act">' + esc(a.name) + '</div><div class="when">' + esc(dayLabel(state.run.day)) + " · " + esc(g.time) + " · " + esc(a.where) + '</div></div><span class="chip good">' + g.final.length + " going</span></div>");
      if (g.magic && g.magic.headline) out.push('<p class="headline">' + esc(g.magic.headline) + "</p>");
      out.push('<div class="msgs">');
      for (var m = 0; m < g.final.length; m++) {
        var id = g.final[m], text = "";
        if (g.magic && g.magic.messages) text = g.magic.messages[id] || "";
        out.push('<div class="msg"><div class="to">To ' + esc(nameOf(id)) + ' <span class="muted">· ' + esc(PEOPLE[id].age) + ", " + esc(PEOPLE[id].archetype) + "</span></div><p>" + esc(text || "(message not written)") + "</p></div>");
      }
      out.push('</div><button class="link" data-act="goto" data-g="' + g.id + '">See the negotiation</button></article>');
    }
    if (!any) out.push('<div class="empty">No group came together in this run.</div>');
    var dropped = [];
    for (var j = 0; j < state.run.groups.length; j++) { if (state.run.groups[j].status === "dropped") dropped.push(state.run.groups[j]); }
    if (dropped.length > 0) {
      out.push('<h3 class="minor">Proposed but didn\'t come together (' + dropped.length + ")</h3>");
      for (var k = 0; k < dropped.length; k++) out.push('<div class="row"><b>' + esc(ACTS[dropped[k].activity].name) + "</b> " + esc(dropped[k].time) + ' <span class="muted">' + esc(dropped[k].dropReason || "") + '</span> <button class="link" data-act="goto" data-g="' + dropped[k].id + '">why</button></div>');
    }
    return out.join("");
  }

  function spokes(g) {
    // the hub in the middle, one line to each agent; there is never a line between agents
    var ids = [];
    for (var i = 0; i < g.members.length; i++) ids.push(g.members[i].id);
    var w = 300, h = 196, cx = 150, cy = 92, r = 60;
    var out = ['<svg class="spokes" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="The matchmaker in the middle, talking to each agent separately">'];
    for (var j = 0; j < ids.length; j++) {
      var ang = -Math.PI / 2 + (2 * Math.PI * j) / ids.length;
      var x = cx + r * Math.cos(ang) * 1.6, y = cy + r * Math.sin(ang);
      var st = member(g, ids[j]).state;
      out.push('<line x1="' + cx + '" y1="' + cy + '" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '" class="sp-' + st + '"/>');
      out.push('<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="13" class="node-' + st + '"/>');
      out.push('<text x="' + x.toFixed(1) + '" y="' + (y + 27).toFixed(1) + '" class="lbl">' + esc(first(ids[j])) + "</text>");
    }
    out.push('<circle cx="' + cx + '" cy="' + cy + '" r="22" class="hub-node"/><text x="' + cx + '" y="' + (cy + 4) + '" class="hub-lbl">hub</text></svg>');
    return out.join("");
  }
  function negotiationPanel() {
    if (!state.run) return noRun();
    var out = ["<h2>Negotiation</h2>", '<p class="lede">Every message between the matchmaker and an agent, word for word. Lines go only from the hub to each agent: agents never see or talk to each other.</p>'];
    if (state.run.plan && state.run.plan.thoughts) out.push('<p class="thoughts"><b>Matchmaker, planning:</b> ' + esc(state.run.plan.thoughts) + "</p>");
    if (state.run.resolve && state.run.resolve.thoughts) out.push('<p class="thoughts"><b>Matchmaker, after round 1:</b> ' + esc(state.run.resolve.thoughts) + "</p>");
    for (var i = 0; i < state.run.groups.length; i++) {
      var g = state.run.groups[i], a = ACTS[g.activity];
      var chip = '<span class="chip">negotiating</span>';
      if (g.status === "locked") chip = '<span class="chip good">locked · ' + g.final.length + "</span>";
      if (g.status === "dropped") chip = '<span class="chip bad">dropped</span>';
      out.push('<section class="neg" id="neg-' + g.id + '"><div class="neg-head"><div><div class="act">' + esc(g.id + " · " + a.name) + '</div><div class="when">' + esc(g.time) + " · " + esc(a.where) + "</div>");
      if (g.why) out.push('<div class="why">' + esc(g.why) + "</div>");
      out.push("</div>" + chip + "</div>");
      out.push('<div class="neg-body">' + spokes(g) + '<div class="thread">');
      for (var t = 0; t < g.thread.length; t++) {
        var e = g.thread[t];
        if (e.from === "hub") out.push('<div class="bub hub"><span class="by">Matchmaker → ' + esc(first(e.to)) + "'s agent · round " + e.round + "</span>" + esc(e.text) + "</div>");
        else if (e.from === "agent") {
          var extra = "";
          if (e.answer === "counter" && e.counter) extra = ' <span class="counter">counter: ' + esc(e.counter) + "</span>";
          out.push('<div class="bub agent"><span class="by">' + esc(first(e.by)) + "'s agent → matchmaker · <b class=\"ans " + esc(e.answer) + '">' + esc(String(e.answer).toUpperCase()) + "</b></span>" + esc(e.text) + extra + "</div>");
        } else out.push('<div class="bub sys">' + esc(e.text) + "</div>");
      }
      if (g.thread.length === 0) out.push('<div class="muted small">Waiting to ask.</div>');
      out.push("</div></div></section>");
    }
    return out.join("");
  }

  function tally(act, iso, part) {
    // why each neighbor is not in this room, counted
    var counts = {}, keys = [];
    for (var n = 0; n < DATA.people.length; n++) {
      var f = fit(DATA.people[n], act, iso, part);
      if (f.why === null) continue;
      var why = f.why;
      if (why.indexOf("dislikes") === 0) why = "dislikes it";
      if (!counts[why]) { counts[why] = 0; keys.push(why); }
      counts[why] += 1;
    }
    keys.sort(function (x, y) { return counts[y] - counts[x]; });
    var out = [];
    for (var i = 0; i < keys.length; i++) out.push(keys[i] + " " + counts[keys[i]]);
    return out.join(" · ");
  }
  function reasonIn(id, act) {
    var p = PEOPLE[id], likes = [];
    for (var i = 0; i < p.likes.length; i++) {
      if (has(act.tags, p.likes[i].tag)) {
        var how = "up for";
        if (p.likes[i].weight === 2) how = "likes";
        if (p.likes[i].weight === 3) how = "loves";
        likes.push(how + " " + words(p.likes[i].tag));
      }
    }
    return likes.join(", ");
  }
  function breakRoomPanel() {
    var slots = breakRoom(ui.day);
    var n = peopleWithAnOption(slots);
    var out = ["<h2>Break rooms · " + esc(dayLabel(ui.day)) + "</h2>"];
    out.push('<div class="rules"><p><b>How a break room is made.</b> A break room is one activity at one time of day, like <i>Paddle Lake Sawyer, Sunday afternoon</i>. Before any AI is involved, code builds one for every activity running that day and checks all ' +
      DATA.people.length + " neighbors against the same rules, in order:</p><ol>" +
      "<li>the activity runs that month, that day and at that time of day</li>" +
      "<li>the person's calendar is free then</li>" +
      "<li>it's within their budget</li>" +
      "<li>they don't dislike it</li>" +
      "<li>they don't avoid anything about it (crowds, early mornings, loud places, late nights, long drives…)</li>" +
      "<li>they actually like it: how much sets their keenness</li></ol>" +
      "<p>Everyone who passes is in the room, keenest first. The orchestrator gets these rooms as its starting point and can only invite people who are in them.</p></div>");
    out.push('<p class="lede"><b>' + slots.length + " break rooms</b> for " + esc(dayLabel(ui.day)) + "; <b>" + n + " of " + DATA.people.length + "</b> neighbors are in at least one.</p>");
    out.push('<div class="slots">');
    for (var i = 0; i < slots.length; i++) {
      var s = slots[i], a = ACTS[s.activity], rows = [];
      for (var j = 0; j < s.candidates.length; j++) {
        var c = s.candidates[j];
        rows.push("<li><b>" + esc(nameOf(c.id)) + '</b> <span class="muted">' + esc(PEOPLE[c.id].age + ", " + PEOPLE[c.id].archetype) + "</span> · " + esc(reasonIn(c.id, a)) + ' <span class="chip">' + c.score + "</span></li>");
      }
      out.push('<details class="slot"><summary><div class="slot-head"><b>' + esc(a.name) + '</b><span class="chip">' + esc(s.part) + '</span><span class="chip good">' + s.candidates.length +
        ' in the room</span></div><div class="muted small">' + esc(a.where) + "</div></summary>" +
        '<ol class="in">' + rows.join("") + "</ol>" +
        '<p class="small muted"><b>Not in the room:</b> ' + esc(tally(a, ui.day, s.part)) + "</p></details>");
    }
    out.push("</div>");
    return out.join("");
  }

  function orchestratorPanel() {
    if (!state.run) return noRun();
    var calls = listOr(state.run.calls);
    var showAgents = ui.showAgents === true;
    var out = ["<h2>What the orchestrator did</h2>", '<p class="lede">Every call to Claude in this run, word for word: exactly what it was sent and exactly what it answered. The orchestrator\'s calls are shown first; switch on agents to see all ' + calls.length + " calls.</p>"];
    var label = "Show agents' calls too";
    if (showAgents) label = "Orchestrator only";
    out.push('<p><button class="btn" data-act="toggle-agents">' + label + "</button></p>");
    var shown = 0;
    for (var i = 0; i < calls.length; i++) {
      var c = calls[i];
      var isAgent = c.kind === "agent reply";
      if (isAgent && !showAgents) continue;
      shown += 1;
      var who = "Orchestrator";
      if (isAgent) who = "Agent";
      var secs = Math.round(c.ms / 100) / 10;
      var head = who + " · " + c.kind + " · " + c.tier + " tier · " + secs + "s";
      if (c.error) head = head + " · FAILED (" + c.error + ")";
      out.push('<details class="call"><summary>' + esc(head) + '</summary><div class="callpart">What it was sent</div><pre>' + esc(c.prompt) +
        '</pre><div class="callpart">What it answered</div><pre>' + esc(c.reply || "(no answer)") + "</pre></details>");
    }
    if (shown === 0) out.push('<div class="empty">No calls recorded in this run.</div>');
    return out.join("");
  }

  function peoplePanel() {
    var out = ["<h2>People</h2>", '<p class="lede">' + DATA.people.length + " emulated adults of " + esc(DATA.neighborhood) + ", shaped like the city's census profile (age mix, households with kids, income). Each line is what they told their own agent. Free on " + esc(dayLabel(ui.day)) + " shown on the right.</p>"];
    out.push('<div class="scroll"><table class="tbl"><thead><tr><th>Name</th><th>Age</th><th>Week</th><th>Area</th><th>Loves</th><th>Free</th></tr></thead><tbody>');
    for (var i = 0; i < DATA.people.length; i++) {
      var p = DATA.people[i], loves = [];
      for (var k = 0; k < p.likes.length; k++) { if (p.likes[k].weight >= 2) loves.push(words(p.likes[k].tag)); }
      var kids = "";
      if (p.kids_at_home) kids = " · kids";
      out.push("<tr><td>" + esc(p.name) + '</td><td class="num">' + p.age + "</td><td>" + esc(p.archetype + kids) + "</td><td>" + esc(p.area) + "</td><td>" + esc(loves.join(", ")) + "</td><td>" + esc(listOr(p.calendar[ui.day]).join(", ")) + "</td></tr>");
    }
    out.push("</tbody></table></div>");
    return out.join("");
  }
  function activitiesPanel() {
    var days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    var out = ["<h2>Things to do</h2>", '<p class="lede">' + DATA.activities.length + " activities in and around " + esc(DATA.neighborhood) + ": real places and recurring events. Times, prices and seasons are estimates for simulation.</p>"];
    out.push('<div class="scroll"><table class="tbl"><thead><tr><th>Activity</th><th>Where</th><th>Days</th><th>When</th><th>Months</th><th>Cost</th></tr></thead><tbody>');
    for (var i = 0; i < DATA.activities.length; i++) {
      var a = DATA.activities[i], d = [], m = [];
      for (var j = 0; j < a.days.length; j++) d.push(days[a.days[j]]);
      for (var k = 0; k < a.months.length; k++) m.push(MONTH[a.months[k] - 1]);
      var months = m.join(" ");
      if (a.months.length === 12) months = "all year";
      out.push("<tr><td><b>" + esc(a.name) + "</b></td><td>" + esc(a.where) + "</td><td>" + esc(d.join(" ")) + "</td><td>" + esc(a.parts.join(", ")) + "</td><td>" + esc(months) + "</td><td>" + esc(a.cost) + "</td></tr>");
    }
    out.push("</tbody></table></div>");
    return out.join("");
  }
  function logPanel() {
    if (!state.run) return noRun();
    var out = ["<h2>Log</h2>", '<p class="lede">Every step of the last run: code checks, the matchmaker\'s thinking and decisions, and every agent reply. Claude calls: ' + esc(callSummary()) + '.</p><div class="log">'];
    for (var i = 0; i < state.run.log.length; i++) {
      var e = state.run.log[i];
      out.push('<div class="logline"><span class="t">' + esc(e.t.slice(11, 19)) + '</span><span class="who ' + esc(e.actor) + '">' + esc(e.actor + " · " + e.kind) + '</span><span class="x">' + esc(e.text) + "</span></div>");
    }
    out.push('</div><p><button class="btn" data-act="export">Copy the run as JSON</button> <span id="exported" class="muted small"></span></p>');
    return out.join("");
  }
  function callSummary() {
    var calls = state.run.metrics.calls, keys = Object.keys(calls), parts = [];
    for (var i = 0; i < keys.length; i++) {
      var c = calls[keys[i]], avg = 0;
      if (c.n > 0) avg = Math.round(c.ms / c.n / 100) / 10;
      var failed = "";
      if (c.failed) failed = ", " + c.failed + " failed";
      parts.push(keys[i] + " " + c.n + " (avg " + avg + "s" + failed + ")");
    }
    if (parts.length === 0) return "none";
    return parts.join(" · ");
  }


  // ---- the stage: one screen, the town, the hub at work, the plans people get ----------
  var GROUP_COLORS = 8;
  function hash(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) { h = h ^ str.charCodeAt(i); h = (h * 16777619) >>> 0; }
    return h;
  }
  var AREAS = [];
  for (var a0 = 0; a0 < DATA.people.length; a0++) { if (!has(AREAS, DATA.people[a0].area)) AREAS.push(DATA.people[a0].area); }
  var W = 760, H = 440, CX = 380, CY = 222;
  var SPOT = {};
  (function place() {
    // each area gets a slice of the town around the hub; people scatter inside their slice
    var slice = (2 * Math.PI) / AREAS.length;
    for (var i = 0; i < DATA.people.length; i++) {
      var p = DATA.people[i], k = AREAS.indexOf(p.area), h = hash(p.id);
      var ang = -Math.PI / 2 + k * slice + slice * 0.12 + (h % 1000) / 1000 * slice * 0.76;
      var rad = 92 + ((h >>> 10) % 1000) / 1000 * 108;
      SPOT[p.id] = { x: CX + Math.cos(ang) * rad * 1.45, y: CY + Math.sin(ang) * rad };
    }
  })();
  function areaLabel(k) {
    // outside the ring of dots, anchored toward the edge it sits on so it never runs off the page
    var slice = (2 * Math.PI) / AREAS.length, ang = -Math.PI / 2 + (k + 0.5) * slice;
    var x = CX + Math.cos(ang) * 222 * 1.55, y = CY + Math.sin(ang) * 214 + 4, anchor = "middle";
    if (Math.cos(ang) > 0.3) { anchor = "end"; x = W - 6; }
    if (Math.cos(ang) < -0.3) { anchor = "start"; x = 6; }
    return { x: x, y: y, anchor: anchor };
  }
  function timeline(run) {
    // every hub->agent ask and agent->hub reply, in the order they happened
    var ev = [];
    if (!run) return ev;
    for (var i = 0; i < run.groups.length; i++) {
      var g = run.groups[i];
      for (var j = 0; j < g.thread.length; j++) {
        var e = g.thread[j];
        if (e.from === "hub") ev.push({ t: e.t, kind: "ask", g: g, pid: e.to, text: e.text });
        if (e.from === "agent") ev.push({ t: e.t, kind: "reply", g: g, pid: e.by, answer: e.answer, text: e.text });
      }
    }
    ev.sort(function (x, y) { if (x.t < y.t) return -1; if (x.t > y.t) return 1; return 0; });
    return ev;
  }
  function lockedGroups() {
    var out = [];
    if (!state.run) return out;
    for (var i = 0; i < state.run.groups.length; i++) { if (state.run.groups[i].status === "locked") out.push(state.run.groups[i]); }
    return out;
  }
  function showingResults() {
    return state.run && !running && ui.replay === null && lockedGroups().length > 0;
  }
  function townSvg() {
    var ev = timeline(state.run), upto = ev.length;
    if (ui.replay !== null) upto = ui.replay.i;
    var st = {}, recent = [];
    for (var i = 0; i < upto; i++) {
      var e = ev[i];
      if (e.kind === "ask") st[e.pid] = "asked";
      else st[e.pid] = e.answer;
      if (i >= upto - 8) recent.push(e);
    }
    var groupOf = {}, locked = lockedGroups();
    if (showingResults()) {
      for (var g = 0; g < locked.length; g++) {
        for (var m = 0; m < locked[g].final.length; m++) groupOf[locked[g].final[m]] = g % GROUP_COLORS;
      }
    }
    var busy = running !== null || ui.replay !== null;
    var out = ['<svg class="town" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Black Diamond: the Clawnly hub in the middle, each neighbor\'s agent around it by area">'];
    for (var k = 0; k < AREAS.length; k++) {
      var l = areaLabel(k);
      out.push('<text x="' + l.x.toFixed(0) + '" y="' + l.y.toFixed(0) + '" text-anchor="' + l.anchor + '" class="area">' + esc(AREAS[k]) + "</text>");
    }
    for (var r = 0; r < recent.length; r++) {
      var s0 = SPOT[recent[r].pid];
      var cls = "ray-ask";
      if (recent[r].kind === "reply") cls = "ray-" + recent[r].answer;
      out.push('<line x1="' + CX + '" y1="' + CY + '" x2="' + s0.x.toFixed(1) + '" y2="' + s0.y.toFixed(1) + '" class="ray ' + cls + '"/>');
    }
    for (var n = 0; n < DATA.people.length; n++) {
      var id = DATA.people[n].id, spot = SPOT[id], c = "dot";
      if (groupOf[id] !== undefined) c = "dot g" + groupOf[id];
      else if (st[id]) c = "dot d-" + st[id];
      else if (showingResults()) c = "dot d-quiet";
      out.push('<circle cx="' + spot.x.toFixed(1) + '" cy="' + spot.y.toFixed(1) + '" r="5" class="' + c + '"><title>' + esc(nameOf(id)) + "</title></circle>");
    }
    var face = "hub";
    if (busy) face = "hub busy";
    out.push('<g class="' + face + '"><circle cx="' + CX + '" cy="' + CY + '" r="44" class="halo"/><circle cx="' + CX + '" cy="' + CY + '" r="32" class="head"/>' +
      '<ellipse cx="' + (CX - 10) + '" cy="' + (CY - 5) + '" rx="3.2" ry="4.4" class="eye"/><ellipse cx="' + (CX + 10) + '" cy="' + (CY - 5) + '" rx="3.2" ry="4.4" class="eye"/>' +
      '<path d="M' + (CX - 10) + " " + (CY + 8) + " Q" + CX + " " + (CY + 17) + " " + (CX + 10) + " " + (CY + 8) + '" class="smile"/>' +
      '<text x="' + CX + '" y="' + (CY + 62) + '" class="hub-name">Clawnly</text></g>');
    out.push("</svg>");
    return out.join("");
  }
  function headline() {
    var c = counts();
    if (running) return { big: status || "Clawnly is at work…", small: "Asking each neighbor's agent, one at a time. Agents never talk to each other." };
    if (ui.replay !== null) {
      var ev = timeline(state.run), e = ev[Math.max(0, ui.replay.i - 1)];
      if (!e) return { big: "Opening the break rooms…", small: "" };
      var act = ACTS[e.g.activity].name;
      if (e.kind === "ask") return { big: "Clawnly \u2192 " + first(e.pid) + "'s agent", small: act + ": " + e.text };
      return { big: first(e.pid) + "'s agent: " + String(e.answer).toUpperCase(), small: e.text };
    }
    if (state.run && lockedGroups().length > 0) {
      return { big: c.planned + " neighbors have plans for " + dayLabel(state.run.day) + ".",
               small: c.locked + " small groups, " + c.asked + " private conversations with agents, 0 between agents." };
    }
    if (state.run) return { big: "No group came together this time.", small: "Open Behind the scenes to see why." };
    return { big: DATA.people.length + " neighbors. " + DATA.activities.length + " things to do. Who does what tomorrow?",
             small: "Each neighbor told their own agent what they like and when they're free. Clawnly talks to every agent and brings back the plans." };
  }
  function renderStage() {
    var root = document.getElementById("root");
    var h = headline();
    var out = ['<div class="wrap stage-wrap"><header class="hero">'];
    out.push('<div class="hero-top"><h1>Run <span>Clawnly</span></h1><button class="link" data-act="details">Behind the scenes \u2192</button></div>');
    out.push('<p class="where">' + esc(DATA.neighborhood) + "</p>");
    out.push('<p class="big" aria-live="polite">' + esc(h.big) + '</p><p class="small-line">' + esc(h.small) + "</p>");
    out.push('<div class="actions"><select id="day" class="sel chipsel" aria-label="Plan for">');
    for (var i = 0; i < DATA.days.length; i++) out.push('<option value="' + DATA.days[i] + '"' + selectedIf(ui.day === DATA.days[i]) + ">" + esc(dayLabel(DATA.days[i])) + "</option>");
    out.push("</select>");
    if (canStart()) {
      var label = "Find plans for " + dayLabel(ui.day).split(" ")[0], dis = "";
      if (running) { label = "Working…"; dis = " disabled"; }
      out.push('<button class="btn primary big-btn" data-act="run"' + dis + ">" + esc(label) + "</button>");
      if (running && !SERVER) out.push('<button class="btn" data-act="stop">Stop</button>');
    }
    if (state.run && !running && timeline(state.run).length > 0) {
      var rl = "Replay how it happened";
      if (ui.replay !== null) rl = "Skip to the plans";
      out.push('<button class="btn big-btn" data-act="replay">' + rl + "</button>");
    }
    if (!state.run && !canStart()) out.push('<span class="small-line">' + esc(readOnlyLine()) + "</span>");
    out.push("</div></header>");
    out.push('<section class="theater">' + townSvg() + '<div class="legend"><span><i class="k-ask"></i>asking</span><span><i class="k-yes"></i>yes</span><span><i class="k-counter"></i>counter</span><span><i class="k-no"></i>no</span></div></section>');
    if (showingResults()) out.push(resultsView());
    if (saveNote && !running) out.push('<p class="small-line">' + esc(saveNote) + "</p>");
    out.push("</div>");
    if (ui.sheet) out.push(sheetView());
    root.innerHTML = out.join("");
  }
  function initials(id) {
    var parts = nameOf(id).split(" ");
    var out = parts[0].charAt(0);
    if (parts.length > 1) out += parts[1].charAt(0);
    return out;
  }
  function resultsView() {
    var locked = lockedGroups();
    if (!ui.picked || !PEOPLE[ui.picked]) ui.picked = locked[0].final[0];
    var out = ['<section class="results"><div class="cards">'];
    out.push('<h2>The plans</h2>');
    for (var i = 0; i < locked.length; i++) {
      var g = locked[i], a = ACTS[g.activity], faces = [];
      for (var m = 0; m < g.final.length; m++) faces.push('<span class="face g' + (i % GROUP_COLORS) + '" title="' + esc(nameOf(g.final[m])) + '">' + esc(initials(g.final[m])) + "</span>");
      out.push('<button class="card c' + (i % GROUP_COLORS) + '" data-act="sheet" data-g="' + g.id + '"><span class="card-act">' + esc(a.name) + '</span><span class="card-when">' + esc(g.time + " \u00b7 " + a.where) +
        '</span><span class="faces">' + faces.join("") + '</span><span class="card-how">How it came together \u2192</span></button>');
    }
    out.push("</div>" + phoneView(locked) + "</section>");
    return out.join("");
  }
  function groupOfPerson(id) {
    var locked = lockedGroups();
    for (var i = 0; i < locked.length; i++) { if (has(locked[i].final, id)) return locked[i]; }
    return null;
  }
  function phoneView(locked) {
    var id = ui.picked, g = groupOfPerson(id), msg = "";
    if (g && g.magic && g.magic.messages) msg = g.magic.messages[id] || "";
    var out = ['<div class="phone-col"><label for="pick" class="small-line">Open someone\'s phone</label><select id="pick" class="sel">'];
    for (var i = 0; i < locked.length; i++) {
      for (var m = 0; m < locked[i].final.length; m++) {
        var pid = locked[i].final[m];
        out.push('<option value="' + pid + '"' + selectedIf(pid === id) + ">" + esc(nameOf(pid) + " \u00b7 " + ACTS[locked[i].activity].name) + "</option>");
      }
    }
    out.push('</select><div class="phone"><div class="phone-top"><span class="av">C</span><div><b>Clawnly</b><span>for ' + esc(first(id)) + "</span></div></div>");
    out.push('<div class="chat"><div class="bubble-in">' + esc(msg || "Your plan is ready.") + '</div>');
    var answer = ui.answers[id];
    if (answer) out.push('<div class="bubble-out">' + esc(answer) + "</div>");
    out.push('</div><div class="replies"><button class="pill" data-act="answer" data-v="I\'m in!">I\'m in</button><button class="pill" data-act="answer" data-v="Not this time.">Not this time</button></div></div>');
    out.push('<p class="small-line">A preview of the one message ' + esc(first(id)) + " gets. Nothing is sent.</p></div>");
    return out.join("");
  }
  function sheetView() {
    var g = null;
    for (var i = 0; i < state.run.groups.length; i++) { if (state.run.groups[i].id === ui.sheet) g = state.run.groups[i]; }
    if (!g) return "";
    var a = ACTS[g.activity];
    var out = ['<div class="sheet-back" data-act="close"></div><div class="sheet" role="dialog" aria-label="How this plan came together"><button class="link close" data-act="close">Close</button>'];
    out.push('<h2>' + esc(a.name) + '</h2><p class="small-line">' + esc(dayLabel(state.run.day) + " \u00b7 " + g.time + " \u00b7 " + a.where) + "</p>");
    if (g.why) out.push('<p class="thoughts"><b>Why Clawnly picked this group:</b> ' + esc(g.why) + "</p>");
    out.push('<div class="neg-body">' + spokes(g) + '<div class="thread">');
    for (var t = 0; t < g.thread.length; t++) {
      var e = g.thread[t];
      if (e.from === "hub") out.push('<div class="bub hub"><span class="by">Clawnly \u2192 ' + esc(first(e.to)) + "'s agent</span>" + esc(e.text) + "</div>");
      else if (e.from === "agent") {
        var extra = "";
        if (e.answer === "counter" && e.counter) extra = ' <span class="counter">counter: ' + esc(e.counter) + "</span>";
        out.push('<div class="bub agent"><span class="by">' + esc(first(e.by)) + "'s agent \u2192 Clawnly \u00b7 <b class=\"ans " + esc(e.answer) + '">' + esc(String(e.answer).toUpperCase()) + "</b></span>" + esc(e.text) + extra + "</div>");
      }
    }
    out.push("</div></div></div>");
    return out.join("");
  }
  function startReplay() {
    var n = timeline(state.run).length;
    if (n === 0) return;
    // about 25 seconds, however big the run
    var step = Math.max(35, Math.min(260, Math.round(25000 / n)));
    ui.replay = { i: 0, timer: null };
    ui.sheet = null;
    function tick() {
      if (ui.replay === null) return;
      ui.replay.i += 1;
      if (ui.replay.i > n) { ui.replay = null; render(); return; }
      render();
      ui.replay.timer = setTimeout(tick, step);
    }
    render();
    ui.replay.timer = setTimeout(tick, 600);
  }
  function stopReplay() {
    if (ui.replay && ui.replay.timer) clearTimeout(ui.replay.timer);
    ui.replay = null;
    render();
  }

  // ---- events -----------------------------------------------------------------
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest("[data-act]");
    if (!el) return;
    var act = el.getAttribute("data-act");
    if (act === "tab") { ui.tab = el.getAttribute("data-tab"); render(); return; }
    if (act === "details") { ui.view = "details"; render(); window.scrollTo(0, 0); return; }
    if (act === "stage") { ui.view = "stage"; render(); window.scrollTo(0, 0); return; }
    if (act === "replay") { if (ui.replay !== null) stopReplay(); else startReplay(); return; }
    if (act === "sheet") { ui.sheet = el.getAttribute("data-g"); render(); return; }
    if (act === "close") { ui.sheet = null; render(); return; }
    if (act === "answer") { ui.answers[ui.picked] = el.getAttribute("data-v"); render(); return; }
    if (act === "toggle-agents") { ui.showAgents = ui.showAgents !== true; render(); return; }
    if (act === "run") { run(); return; }
    if (act === "stop") { if (running && running.abort) running.abort(); return; }
    if (act === "goto") {
      ui.tab = "negotiation"; render();
      var target = document.getElementById("neg-" + el.getAttribute("data-g"));
      if (target) target.scrollIntoView({ block: "start" });
      return;
    }
    if (act === "export") {
      var note = document.getElementById("exported");
      try {
        navigator.clipboard.writeText(JSON.stringify(state.run, null, 2)).then(function () { if (note) note.textContent = "Copied."; },
          function () { if (note) note.textContent = "Your browser blocked copying."; });
      } catch (e) { if (note) note.textContent = "Your browser blocked copying."; }
    }
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && ui.sheet) { ui.sheet = null; render(); }
  });
  document.addEventListener("change", function (ev) {
    if (ev.target.id === "day") { ui.day = ev.target.value; render(); }
    if (ev.target.id === "maxg") { ui.maxGroups = ev.target.value; render(); }
    if (ev.target.id === "pick") { ui.picked = ev.target.value; render(); }
  });

  // ---- boot -------------------------------------------------------------------
  render();
  if (SERVER) poll();
  else if (window.claude && typeof window.claude.use === "function") {
    window.claude.use("sample").then(function (fn) { sample = fn; render(); }, function () { });
    window.claude.use("artifact").then(function (api) { artifactApi = api; }, function () { });
    window.claude.use("user").then(function (u) {
      if (!u) return;
      u.isOwner().then(function (v) { isOwner = v === true; render(); }, function () { });
    }, function () { });
  }
})();
