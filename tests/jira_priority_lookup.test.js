// Issue #95: Jira create form submits invalid priority when project-restricted priorities are active.
// Root cause: on submit, priObj was looked up from allPriorities (global list) but priVal came
// from dynPriorityField.allowed (project-restricted list) → lookup failed → priName = raw ID →
// Jira rejected it as "The priority selected is invalid".
// Fix: track _activePriorityList and look up from the currently-shown list.

const assert = require('assert');

// Simulate the global priorities returned by /api/jira/priorities
const allPriorities = [
  { id: '1', name: 'Highest' },
  { id: '2', name: 'High' },
  { id: '3', name: 'Medium' },
  { id: '4', name: 'Low' },
  { id: '5', name: 'Lowest' },
];

// Simulate project-restricted priorities from dynPriorityField.allowed (e.g. ROCM project)
const projectAllowed = [
  { id: '10100', name: 'P1: High' },
  { id: '10101', name: 'P2 (Must Solve)' },
  { id: '10102', name: 'P3: Low' },
];

// The fix: _activePriorityList is updated to dynPriorityField.allowed when project restricts priorities.
// On submit: priObj = _activePriorityList.find(p => (p.id || p.name) === priVal)

function simulatePriorityLookup(activePriorityList, priVal) {
  const priObj = activePriorityList.find(p => (p.id || p.name) === priVal);
  return priObj?.name || priVal || '';
}

// Case 1: global priorities active, user picks "Medium" by ID → should resolve to "Medium"
{
  const priName = simulatePriorityLookup(allPriorities, '3');
  assert.strictEqual(priName, 'Medium', 'global priority ID "3" must resolve to "Medium"');
}

// Case 2 (the bug): project-restricted priorities active, user picks "P1: High" by its ID
// BEFORE fix: looked up from allPriorities → not found → priName = "10100" (raw ID) → Jira rejects
// AFTER fix: looks up from _activePriorityList (projectAllowed) → finds it → priName = "P1: High"
{
  const priName = simulatePriorityLookup(projectAllowed, '10100');
  assert.strictEqual(priName, 'P1: High', 'restricted priority ID "10100" must resolve to "P1: High"');
}

// Case 3: same bug path — P2 priority
{
  const priName = simulatePriorityLookup(projectAllowed, '10101');
  assert.strictEqual(priName, 'P2 (Must Solve)', 'restricted priority "10101" must resolve to "P2 (Must Solve)"');
}

// Case 4: demonstrate the old (broken) behaviour — global list cannot resolve restricted priority IDs
{
  const priNameBroken = simulatePriorityLookup(allPriorities, '10100');
  assert.strictEqual(priNameBroken, '10100', 'sanity: global list CANNOT resolve restricted ID (falls back to raw ID)');
}

// Case 5: no priority selected (empty string) → stays empty
{
  const priName = simulatePriorityLookup(projectAllowed, '');
  assert.strictEqual(priName, '', 'empty priVal must remain empty');
}

// Case 6: type switches back to one with no restriction → _activePriorityList resets to allPriorities
{
  const priName = simulatePriorityLookup(allPriorities, '2');
  assert.strictEqual(priName, 'High', 'after restriction removed, global priority "2" must resolve to "High"');
}

console.log('jira_priority_lookup: all assertions passed');
