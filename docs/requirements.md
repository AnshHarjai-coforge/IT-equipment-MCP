# Requirements: IT equipment request handler

Employees ask for IT equipment in plain language. The system looks up who they are and what
they already hold, checks their role's policy, and then approves the request, denies it, or
escalates it to a human reviewer. It never guesses. Anything the records and the rules cannot
settle goes to a human.

**Who decides what.** Every policy decision is made in Python and returned as a verdict with a
written reason. The model reads the request, calls the tools, and relays and explains the
results. It never does the arithmetic and never makes the comparison. The model may move a
decision only toward a human (escalation). It never approves or denies on its own.

## 1. What a request contains

A request arrives as two things:

| Part | Example | Where it comes from |
| --- | --- | --- |
| Employee id | `E001` | Who sent the request, as in any ticket system. It is never read out of the text. |
| Request text | "My laptop is 4 years old and slow, can I get a replacement?" | What the employee wrote. |

From the **text**, the agent reads:

- **the item**, in the catalogue's word. The model maps "MacBook" to `laptop` and "display" or
  "screen" to `monitor`. There is no alias table in code. A word the catalogue doesn't have is
  sent to a human (rule 1 below).
- **which kind of request** it is: an **additional** item (one more, kept alongside what they
  have) or a **replacement** (a new one in place of their oldest, which goes back).
- **the reason**, and any claim in it, such as "it's broken", "I lost it", or a medical need.

From the **records**, never from the text, the system looks up:

- the employee's **role** (`standard`, `engineer` or `manager`)
- their **tenure**, in whole years
- the **equipment on file**, each item with its **age in whole years**

The policy covers *a laptop*, not a brand. A reply never promises a particular make or model.

## 2. Policy rules

Each role may hold up to `max_quantity` of an item at once, and one is replaced after it is
`refresh_years` whole years old.

| Item | standard | engineer | manager |
| --- | --- | --- | --- |
| laptop | 1, replaced after 4 yrs | 1, after 3 yrs | 1, after 2 yrs |
| monitor | 1, after 3 yrs | 2, after 4 yrs | 2, after 3 yrs |
| docking station | not issued | 1, after 4 yrs | 1, after 4 yrs |

The rules live in `data/policies.json`, and a test asserts the whole table, so a change to what
the system approves must be made on purpose.

**The catalogue** is every item that appears under any role: laptop, monitor, docking station.
It is worked out from the policies, never kept as a separate list.

**Counting years.** Ages are counted in completed years, the same way as tenure. A laptop issued
on 2022-03-01 is 3 years old on 2026-02-28 and 4 years old on 2026-03-01. An item issued on
29 February completes each year on 1 March when the year has no 29 February.

## 3. How a request is decided

**Matching.** The item text is lower-cased and trimmed before lookup, so "Monitor " is the same
as "monitor". Nothing beyond that is guessed. Roles must match exactly; an unknown role is an
error, and the error lists the known roles.

**Two answers every time.** The eligibility check always answers both questions, *additional*
and *replacement*, because the wording of a request ("a monitor") often doesn't say which is
meant. The agent uses the answer for the one the employee asked. Each answer is a **verdict**,
`approved`, `denied` or `needs_review`, always with a written reason.

The rules are checked **in this order**, and the first one that applies decides:

1. **No role's policy mentions the item** (say, "standing desk"): both answers are
   `needs_review`. The reason names the items that are covered, so a wrong word can be
   corrected.
2. **The role isn't issued that item** (a standard employee asking for a docking station): both
   answers are `denied`. After rule 1 or 2 there is no limit or replacement period to report,
   so the result gives both as null.
3. **The records show more than the role may hold** (a standard employee on file with two
   monitors): both answers are `needs_review`, because the records disagree with the policy.
4. **Additional:** `approved` if they hold fewer than the limit, otherwise `denied`. A denial
   says in words that there is no date, for example "Another laptop is not issued while
   1 laptop is held, so there is no date on which this changes", so no date is ever invented.
5. **Replacement:**
   - `denied` if they hold none of that item, since there is nothing to replace;
   - `approved` if their oldest one has reached the refresh age;
   - otherwise `denied`, with the date it becomes due (`next_eligible_on`), calculated in
     Python. An item issued on 29 February becomes due on 1 March in a year with no
     29 February.

Examples, for a standard employee holding one laptop:

| Laptop's age | Request | Verdict |
| --- | --- | --- |
| 4 years | replacement | `approved`: standard laptops are replaced after 4 years |
| 3 years | replacement | `denied`, with the date it reaches 4 years |
| any | additional | `denied`: another laptop is not issued while one is held, and no date applies |

## 4. What counts as ambiguous

An ambiguous request is escalated to a human rather than decided.

| Detected by | Cases |
| --- | --- |
| Python, from the records | the item isn't covered by any policy (rule 1); the records disagree with the policy (rule 3) |
| The model, from the wording | the request claims something the records can't show (broken, lost, stolen, a medical need); it can't tell which item, or whether an additional item or a replacement is meant; it asks for several things at once |

For example, "I dropped my laptop and cracked the screen" is escalated even when the laptop isn't
yet due for replacement. The records can't confirm the damage, and a human should decide.

## 5. Outcomes

Every request ends in exactly one of four outcomes.

| Outcome | When | What happens |
| --- | --- | --- |
| **approved** | the verdict for the question the employee asked is `approved`, and nothing in the wording is ambiguous | the reply confirms the item, and promises nothing the records don't show: no brand, no delivery date |
| **denied** | the verdict for the question asked is `denied`, and nothing in the wording is ambiguous | the reply gives the reason, and the date it becomes due if there is one |
| **escalated** | the verdict is `needs_review`, or the model finds the wording ambiguous (section 4) | `flag_for_human_review` records the request and the reason; the reply says a person will review it |
| **not processed** | the employee id is unknown | nothing can be checked and nothing can be flagged; the reply asks for a valid id |

## 6. Tenure

Tenure is reported by `get_employee_info`, but **no rule uses it** for now. Any future rule that
depends on tenure needs its own test.
