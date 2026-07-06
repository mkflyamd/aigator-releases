// Issue #145: Jira form field serialization — Fix A (submit loop) and Fix C (pre-fill extractor)
//
// Fix A: submit loop must record fieldSchemas and send plain string for doc fields
// Fix B: _buildJiraFieldFor must render textarea for doc fields (DOM test, skipped here)
// Fix C: _adfNodeToText must recursively extract plain text from ADF; pre-fill extractor
//        must handle string/number/array/ADF-object/option-object inputs correctly

'use strict';

const assert = require('assert');

// ── Functions under test ──────────────────────────────────────────────────────

const BLOCK_TYPES = new Set([
  'paragraph', 'heading', 'blockquote', 'codeBlock',
  'bulletList', 'orderedList', 'listItem', 'rule',
]);

function _adfNodeToText(node) {
  if (!node || typeof node !== 'object') return '';
  if (node.type === 'text') return node.text || '';
  if (node.type === 'mention') return (node.attrs && (node.attrs.text || node.attrs.id)) || '';
  if (node.type === 'hardBreak') return '\n';
  const children = Array.isArray(node.content) ? node.content : [];
  const childText = children.map(_adfNodeToText).join('');
  return BLOCK_TYPES.has(node.type) ? childText + '\n' : childText;
}

function extractPrefill(v, fieldKey) {
  if (v === undefined || v === null) return '';
  if (typeof v === 'string' || typeof v === 'number') return String(v);
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') {
    if (v.type === 'doc' && Array.isArray(v.content)) return _adfNodeToText(v).trim();
    if (v.name) return v.name;
    if (v.displayName) return v.displayName;
    if (v.value) return v.value;
    if (v.id) return String(v.id);
    if (v.accountId) return v.accountId;
  }
  return '';
}

function buildFieldSchemas(dynamicFieldBuilders) {
  const schemas = {};
  dynamicFieldBuilders.forEach(({ field, val }) => {
    if (val) schemas[field.key] = field.type || 'string';
  });
  return schemas;
}

function serializeFieldValue(field, val) {
  const fsys = field.system || field.key;
  if (field.type === 'user' || fsys === 'reporter' || fsys === 'assignee') {
    return { accountId: val };
  } else if (field._isDynamic) {
    const opt = (field.allowed || []).find(o => o.id === val);
    const label = opt ? opt.name || val : val;
    return { selectedOptionsList: [{ label, viewLabel: label, value: val }], asArray: [val] };
  } else if (field.type === 'option') {
    return { id: val };
  } else if (field.type === 'array') {
    return val.split ? val.split(',').map(s => s.trim()).filter(Boolean).map(s => ({ id: s })) : [{ id: String(val) }];
  } else if (field.type === 'object') {
    return { asArray: [val] };
  } else {
    // doc fields and plain string fields both send the raw string value;
    // the backend applies ADF wrapping for doc fields based on field_schemas.
    return val;
  }
}

// ═══════════════════════════════════════════════════════════
// Fix C — _adfNodeToText recursive walker
// ═══════════════════════════════════════════════════════════

// text node
{
  const node = { type: 'text', text: 'Hello' };
  const result = _adfNodeToText(node);
  assert.strictEqual(result, 'Hello', 'text node: returns text');
}

// hardBreak node → newline
{
  const node = { type: 'hardBreak' };
  const result = _adfNodeToText(node);
  assert.strictEqual(result, '\n', 'hardBreak: returns newline');
}

// mention node → attrs.text
{
  const node = { type: 'mention', attrs: { text: '@alice', id: '12345' } };
  const result = _adfNodeToText(node);
  assert.strictEqual(result, '@alice', 'mention: returns attrs.text');
}

// mention node with no attrs.text → falls back to attrs.id
{
  const node = { type: 'mention', attrs: { id: '12345' } };
  const result = _adfNodeToText(node);
  assert.strictEqual(result, '12345', 'mention without text: returns attrs.id');
}

// paragraph → childText + newline
{
  const node = {
    type: 'paragraph',
    content: [{ type: 'text', text: 'Hello world' }],
  };
  const result = _adfNodeToText(node);
  assert.strictEqual(result, 'Hello world\n', 'paragraph: appends newline');
}

// doc root → children joined, no extra newline for doc itself
{
  const node = {
    type: 'doc',
    version: 1,
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Para 1' }] },
      { type: 'paragraph', content: [{ type: 'text', text: 'Para 2' }] },
    ],
  };
  const result = _adfNodeToText(node).trim();
  assert.strictEqual(result, 'Para 1\nPara 2', 'doc: two paragraphs separated by newline');
}

// bulletList with listItems
{
  const node = {
    type: 'bulletList',
    content: [
      { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Item 1' }] }] },
      { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Item 2' }] }] },
    ],
  };
  const result = _adfNodeToText(node);
  assert.ok(result.includes('Item 1'), 'bulletList: contains Item 1');
  assert.ok(result.includes('Item 2'), 'bulletList: contains Item 2');
}

// codeBlock — extracts inner text
{
  const node = {
    type: 'codeBlock',
    content: [{ type: 'text', text: 'const x = 1;' }],
  };
  const result = _adfNodeToText(node);
  assert.ok(result.includes('const x = 1;'), 'codeBlock: inner text extracted');
}

// heading — extracts text
{
  const node = {
    type: 'heading',
    attrs: { level: 2 },
    content: [{ type: 'text', text: 'My Heading' }],
  };
  const result = _adfNodeToText(node);
  assert.ok(result.includes('My Heading'), 'heading: text extracted');
}

// node with no content — returns empty string without throwing
{
  const node = { type: 'rule' };
  const result = _adfNodeToText(node);
  assert.strictEqual(typeof result, 'string', 'empty node: returns string without throwing');
}

// ═══════════════════════════════════════════════════════════
// Fix C — extractPrefill (the IIFE that replaces String())
// ═══════════════════════════════════════════════════════════

// undefined → ''
{
  const result = extractPrefill(undefined, 'f1');
  assert.strictEqual(result, '', 'undefined: returns empty string');
}

// null → ''
{
  const result = extractPrefill(null, 'f1');
  assert.strictEqual(result, '', 'null: returns empty string');
}

// plain string passthrough
{
  const result = extractPrefill('hello', 'f1');
  assert.strictEqual(result, 'hello', 'string: returns as-is');
}

// number → string
{
  const result = extractPrefill(42, 'f1');
  assert.strictEqual(result, '42', 'number: converts to string');
}

// array of strings → comma-joined (Fix v1 regression that was caught)
{
  const result = extractPrefill(['a', 'b', 'c'], 'f1');
  assert.strictEqual(result, 'a, b, c', 'string array: joins with comma-space');
}

// ADF doc object → plain text via _adfNodeToText
{
  const adf = {
    type: 'doc', version: 1,
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Step 1' }] },
    ],
  };
  const result = extractPrefill(adf, 'customfield_10039');
  assert.strictEqual(result.trim(), 'Step 1', 'ADF doc: extracts plain text');
}

// option object {id, name} → name
{
  const result = extractPrefill({ id: '10001', name: 'Bug' }, 'f1');
  assert.strictEqual(result, 'Bug', 'option {name}: returns name');
}

// priority object {name} → name
{
  const result = extractPrefill({ name: 'High' }, 'f1');
  assert.strictEqual(result, 'High', 'priority {name}: returns name');
}

// user object {displayName, accountId} → displayName
{
  const result = extractPrefill({ displayName: 'Alice Smith', accountId: 'abc123' }, 'f1');
  assert.strictEqual(result, 'Alice Smith', 'user {displayName}: returns displayName');
}

// object with only id → string id
{
  const result = extractPrefill({ id: '99' }, 'f1');
  assert.strictEqual(result, '99', '{id}: returns string id');
}

// object with only accountId → accountId string
{
  const result = extractPrefill({ accountId: 'xyz' }, 'f1');
  assert.strictEqual(result, 'xyz', '{accountId}: returns accountId');
}

// unknown object shape → '' (no throw)
{
  const result = extractPrefill({ foo: 'bar' }, 'f1');
  assert.strictEqual(result, '', 'unknown object: returns empty string without throwing');
}

// ═══════════════════════════════════════════════════════════
// Fix A — fieldSchemas recording and doc field serialization
// ═══════════════════════════════════════════════════════════

// doc field: serializeFieldValue returns plain string (backend wraps to ADF)
{
  const field = { key: 'customfield_10039', type: 'doc', name: 'Steps to Reproduce' };
  const result = serializeFieldValue(field, 'Step 1\nStep 2');
  assert.strictEqual(result, 'Step 1\nStep 2', 'doc field: submit sends plain string');
}

// fieldSchemas records type for every field with a value
{
  const builders = [
    { field: { key: 'customfield_10039', type: 'doc' }, val: 'some text' },
    { field: { key: 'customfield_10050', type: 'option' }, val: '10001' },
    { field: { key: 'customfield_10060', type: 'string' }, val: 'plain' },
  ];
  const schemas = buildFieldSchemas(builders);
  assert.strictEqual(schemas['customfield_10039'], 'doc', 'fieldSchemas: doc type recorded');
  assert.strictEqual(schemas['customfield_10050'], 'option', 'fieldSchemas: option type recorded');
  assert.strictEqual(schemas['customfield_10060'], 'string', 'fieldSchemas: string type recorded');
}

// field with no type defaults to 'string' in schemas
{
  const builders = [{ field: { key: 'customfield_10070' }, val: '5' }];
  const schemas = buildFieldSchemas(builders);
  assert.strictEqual(schemas['customfield_10070'], 'string', 'fieldSchemas: missing type defaults to string');
}

// option field serialization unchanged
{
  const field = { key: 'customfield_10050', type: 'option', name: 'Category' };
  const result = serializeFieldValue(field, '10001');
  assert.deepStrictEqual(result, { id: '10001' }, 'option field: serialized as {id}');
}

// user field serialization unchanged
{
  const field = { key: 'customfield_10055', type: 'user', system: 'reporter', name: 'Reporter' };
  const result = serializeFieldValue(field, 'abc123');
  assert.deepStrictEqual(result, { accountId: 'abc123' }, 'user field: serialized as {accountId}');
}

// array field serialization unchanged
{
  const field = { key: 'customfield_10060', type: 'array', name: 'Components' };
  const result = serializeFieldValue(field, 'frontend,backend');
  assert.deepStrictEqual(result, [{ id: 'frontend' }, { id: 'backend' }], 'array field: split and mapped to [{id}]');
}

// ═══════════════════════════════════════════════════════════
// LLM fallback — _jiraHandoverToAgent prompt construction
// ═══════════════════════════════════════════════════════════

function buildHandoverPrompt(payload, fieldSchemas, errorBody) {
  const fieldLines = [];
  const ef = payload.extra_fields || {};
  Object.entries(ef).forEach(([k, v]) => {
    const schemaType = (fieldSchemas || {})[k] || '';
    const display = (typeof v === 'object') ? JSON.stringify(v) : String(v);
    fieldLines.push(`  ${k} (type: ${schemaType || 'unknown'}): ${display.slice(0, 200)}`);
  });
  return `@jira Please create this Jira ticket using jira_mutate — the form submission failed due to a field format issue. Use jira_get_project_meta first if needed to check field schemas, then call jira_mutate POST issue with correct ADF for any rich-text fields.\n\nProject: ${payload.project}\nSummary: ${payload.summary}\nIssue type: ${payload.issue_type}\nDescription: ${payload.description || '(none)'}\nPriority: ${payload.priority || '(none)'}\nExtra fields:\n${fieldLines.length ? fieldLines.join('\n') : '  (none)'}`;
}

// prompt includes @jira prefix (routes to jira skill)
{
  const prompt = buildHandoverPrompt(
    { project: 'AIVLLM', summary: 'My bug', issue_type: 'Bug', description: 'desc', priority: '10036',
      extra_fields: { customfield_10039: 'Step 1' } },
    { customfield_10039: 'doc' },
    { detail: { field_errors: { customfield_10039: 'Operation value must be an Atlassian Document' } } }
  );
  assert.ok(prompt.startsWith('@jira'), 'handover prompt starts with @jira');
  assert.ok(prompt.includes('AIVLLM'), 'prompt includes project');
  assert.ok(prompt.includes('My bug'), 'prompt includes summary');
  assert.ok(prompt.includes('customfield_10039'), 'prompt includes field key');
  assert.ok(prompt.includes('type: doc'), 'prompt includes schema type');
  assert.ok(prompt.includes('Step 1'), 'prompt includes field value');
  assert.ok(prompt.includes('jira_mutate'), 'prompt instructs agent to use jira_mutate');
}

// extra_fields empty → no field lines shown, no crash
{
  const prompt = buildHandoverPrompt(
    { project: 'X', summary: 'S', issue_type: 'Bug', extra_fields: {} },
    {},
    {}
  );
  assert.ok(typeof prompt === 'string' && prompt.length > 0, 'empty extra_fields: no crash');
}

console.log('jira_field_serialization: all assertions passed');
