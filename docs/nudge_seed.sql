-- Nudge ERD v3.1 seed data. Run once after nudge_schema_v3_1.sql (idempotent: safe to run again).
-- In Django this is the data migration ml 0002_seed_labels (update_or_create) plus the
-- sign-up service that calls nudge_create_default_stages() for every new organization.

-- 1. Classification tasks (global system data)
INSERT INTO label_sets (code, name, is_multi_label) VALUES
  ('priority',     'Priority',     false),   -- exactly one label per email (Req 11.1)
  ('sales_intent', 'Sales intent', true)     -- a reply may carry several intents
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_multi_label = EXCLUDED.is_multi_label;
-- action_type is not seeded: it was removed from the 26 Oct 2026 SRS.

-- 2. Labels. position = display order in the UI.
INSERT INTO labels (label_set_id, code, name, description, position)
SELECT s.id, v.code, v.name, v.description, v.position
FROM label_sets s
JOIN (VALUES
  ('priority', 'needs_you', 'Needs you', 'A person must read or answer this email.', 0),
  ('priority', 'fyi',       'FYI',       'Worth knowing, no action needed.',        1),
  ('priority', 'noise',     'Noise',     'Newsletters, notifications, bulk mail.',  2),
  ('sales_intent', 'meeting_request', 'Meeting request', 'Asks for or agrees to a call or meeting.',            0),
  ('sales_intent', 'pricing_request', 'Pricing request', 'Asks for price, quote or plan details.',              1),
  ('sales_intent', 'objection',       'Objection',       'Raises a concern: price, competitor, timing, fit.',   2),
  ('sales_intent', 'defer',           'Defer',           'Interested but asks to talk later.',                  3),
  ('sales_intent', 'referral',        'Referral',        'Points to another person who should be contacted.',   4),
  ('sales_intent', 'not_interested',  'Not interested',  'Declines, with or without a reason.',                 5),
  ('sales_intent', 'opt_out',         'Opt-out',         'Asks to stop emails. Blocks all further sending.',    6),
  ('sales_intent', 'out_of_office',   'Out of office',   'Automatic away reply, often with a return date.',     7),
  ('sales_intent', 'unclear',         'Unclear',         'A sales reply whose intent cannot be decided.',       8),
  ('sales_intent', 'other',           'Other',           'Not a sales reply (decision D9).',                    9)
) AS v(set_code, code, name, description, position) ON v.set_code = s.code
ON CONFLICT (label_set_id, code) DO UPDATE
  SET name = EXCLUDED.name, description = EXCLUDED.description, position = EXCLUDED.position;

-- 3. Seven default pipeline stages, created for each new organization at sign-up (Req 7.x).
--    outcome: 1 Open, 2 Won, 3 Lost. Called by the sign-up service inside its transaction.
CREATE OR REPLACE FUNCTION nudge_create_default_stages(p_org uuid) RETURNS void LANGUAGE sql AS $$
  INSERT INTO deal_stages (organization_id, name, position, outcome)
  SELECT p_org, v.name, v.position, v.outcome
  FROM (VALUES ('New', 0, 1), ('Contacted', 1, 1), ('Meeting scheduled', 2, 1), ('Proposal', 3, 1),
               ('Negotiation', 4, 1), ('Won', 5, 2), ('Lost', 6, 3)) AS v(name, position, outcome)
  WHERE NOT EXISTS (SELECT 1 FROM deal_stages WHERE organization_id = p_org);
$$;
