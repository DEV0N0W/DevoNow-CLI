"""Small offline regression checks for the acceptance harness itself."""
from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('acceptance', Path(__file__).resolve().parents[1] / 'suite' / 'runner.py')
acceptance = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


class HarnessTests(unittest.TestCase):
    def fresh_state(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(acceptance, 'STATE_FILE', Path(folder) / 'state.json'):
                return acceptance.load_state('current')

    def passed_result(self, test):
        return {'status': 'PASS', 'fingerprint': 'current',
                'harness_version': acceptance.HARNESS_VERSION,
                'test_revision': acceptance.test_revision(test.test_id),
                'provenance': 'AUTOMATED', 'details': 'verified'}

    def all_mandatory_passed(self):
        state = self.fresh_state()
        state['results'] = {test.test_id: self.passed_result(test)
                            for test in acceptance.QUICK_TESTS}
        return state

    def test_source_hash_ignores_target_but_tracks_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Cargo.toml').write_text('a', encoding='utf-8')
            (root / 'target').mkdir()
            (root / 'target' / 'compile-artifact').write_text('x', encoding='utf-8')
            start = acceptance.source_digest(root)
            (root / 'target' / 'compile-artifact').write_text('y', encoding='utf-8')
            self.assertEqual(start, acceptance.source_digest(root))
            (root / 'Cargo.toml').write_text('b', encoding='utf-8')
            self.assertNotEqual(start, acceptance.source_digest(root))

    def test_manual_import_is_identified_and_pinned(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(acceptance, 'STATE_FILE', Path(folder) / 'state.json'):
                state = acceptance.load_state('fingerprint1')
                self.assertEqual('CARRIED_FORWARD', state['carried']['u01_cli_smoke']['status'])
                self.assertEqual('FAIL', state['results']['u01_default_bubblewrap']['status'])
                self.assertEqual('CARRIED_FORWARD', acceptance.get_carried_status(state['carried']['u01_cli_smoke'], 'fingerprint1'))
                self.assertEqual('STALE_PRIOR_EVIDENCE', acceptance.get_carried_status(state['carried']['u01_cli_smoke'], 'fingerprint2'))

    def test_json_write_persists_atomically(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            acceptance.atomic_json(path, {'result': 'PASS'})
            self.assertIn('PASS', path.read_text(encoding='utf-8'))
            self.assertEqual([], list(Path(folder).glob('*.tmp-*')))

    def test_report_keeps_prior_bubblewrap_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(acceptance, 'STATE_FILE', Path(folder) / 'state.json'):
                state = acceptance.load_state('one')
            evaluation = acceptance.evaluate_acceptance(state, 'one')
            report = acceptance.report(state, {
                'platform':'Ubuntu', 'machine':'aarch64','source_sha256':'a', 'binary_sha256':'b', 'apparmor_userns':'1'
            }, 'one', {'executed': 0, 'cached': 0, 'held': 0}, evaluation)
            self.assertIn('u01_default_bubblewrap', report)
            self.assertIn('NOT ACCEPTED', report)
            self.assertIn('CARRIED_FORWARD', report)

    def test_all_mandatory_pass_with_approved_replacement(self):
        state = self.all_mandatory_passed()
        evaluation = acceptance.evaluate_acceptance(state, 'current')
        self.assertEqual('PASS', evaluation['automated_mandatory_gate'])
        self.assertEqual([], evaluation['unresolved_mandatory'])
        self.assertEqual('ACCEPTED', evaluation['full_u01'])
        self.assertEqual('PASS', evaluation['approved_replacement']['status'])
        self.assertEqual([], evaluation['historical_evidence_gaps'])
        self.assertEqual('CARRIED_FORWARD', state['carried']['u01_argument_validation']['status'])

    def test_approved_replacement_needs_current_results(self):
        for test_id in acceptance.APPROVED_ARGUMENT_REPLACEMENT:
            for condition in ('missing', 'stale', 'failed'):
                with self.subTest(test_id=test_id, condition=condition):
                    state = self.all_mandatory_passed()
                    if condition == 'missing':
                        del state['results'][test_id]
                    elif condition == 'stale':
                        state['results'][test_id]['test_revision'] -= 1
                    else:
                        state['results'][test_id]['status'] = 'FAIL'
                    evaluation = acceptance.evaluate_acceptance(state, 'current')
                    self.assertEqual('NOT ACCEPTED', evaluation['full_u01'])
                    self.assertEqual('PENDING', evaluation['approved_replacement']['status'])
                    self.assertIn('u01_argument_validation', evaluation['historical_evidence_gaps'])
                    self.assertIn(test_id, [item['test_id'] for item in evaluation['unresolved_mandatory']])

    def test_mandatory_statuses_are_unresolved(self):
        for status in ('FAIL', 'PENDING', 'STALE', 'SKIPPED', 'BLOCKED'):
            with self.subTest(status=status):
                state = self.all_mandatory_passed()
                state['results']['u01_default_bubblewrap']['status'] = status
                evaluation = acceptance.evaluate_acceptance(state, 'current')
                self.assertEqual('PENDING', evaluation['automated_mandatory_gate'])
                self.assertEqual([{'test_id': 'u01_default_bubblewrap', 'status': status}],
                                 evaluation['unresolved_mandatory'])

    def test_missing_and_stale_mandatory_results(self):
        for change, expected in (('missing', 'PENDING'), ('fingerprint', 'STALE'),
                                 ('revision', 'STALE')):
            with self.subTest(change=change):
                state = self.all_mandatory_passed()
                result = state['results']['u01_default_bubblewrap']
                if change == 'missing':
                    del state['results']['u01_default_bubblewrap']
                elif change == 'fingerprint':
                    result['fingerprint'] = 'old'
                else:
                    result['test_revision'] += 1
                evaluation = acceptance.evaluate_acceptance(state, 'current')
                self.assertIn({'test_id': 'u01_default_bubblewrap', 'status': expected},
                              evaluation['unresolved_mandatory'])

    def test_new_security_checks_must_run(self):
        state = self.all_mandatory_passed()
        security_ids = {test.test_id for test in acceptance.QUICK_TESTS
                        if test.test_id.startswith('u01_default_bubblewrap_')}
        for test_id in security_ids:
            del state['results'][test_id]
        evaluation = acceptance.evaluate_acceptance(state, 'current')
        self.assertEqual(5, len(security_ids))
        self.assertEqual(security_ids,
                         {item['test_id'] for item in evaluation['unresolved_mandatory']})

    def test_optional_extended_check_does_not_block_gate(self):
        evaluation = acceptance.evaluate_acceptance(self.all_mandatory_passed(), 'current')
        self.assertEqual('PASS', evaluation['automated_mandatory_gate'])
        self.assertEqual('PENDING', next(check['status'] for check in evaluation['checks']
                                         if check['test_id'] == 'u01_sandbox_unit_tests'))

    def test_current_evidence_reduces_only_matching_historical_gaps(self):
        evaluation = acceptance.evaluate_acceptance(self.all_mandatory_passed(), 'current')
        self.assertNotIn('u01_binary_execution', evaluation['historical_evidence_gaps'])
        self.assertNotIn('u01_landlock_filesystem', evaluation['historical_evidence_gaps'])
        self.assertNotIn('u01_cli_smoke', evaluation['historical_evidence_gaps'])
        self.assertNotIn('u01_argument_validation', evaluation['historical_evidence_gaps'])

    def test_native_build_requires_success_and_matching_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Cargo.lock').write_text('lock', encoding='utf-8')
            binary = root / 'codex'
            binary.write_text('binary', encoding='utf-8')
            build = {'source_sha256': 'source', 'cargo_lock_sha256': 'lockhash',
                     'binary_sha256': 'binaryhash', 'exit_status': 0,
                     'clean_exit_status': 0,
                     'source_unchanged': True, 'lock_unchanged': True,
                     'binary_architecture': 'ELF 64-bit aarch64', 'log': '/tmp/build.log'}
            ctx = acceptance.Context('current', {'builds': [build]})
            with patch.object(acceptance, 'SOURCE', root), \
                 patch.object(acceptance, 'BINARY', binary), \
                 patch.object(acceptance, 'source_digest', return_value='source'), \
                 patch.object(acceptance, 'digest_file', side_effect=lambda path: 'lockhash' if path.name == 'Cargo.lock' else 'binaryhash'):
                self.assertIn('exit=0', acceptance.test_native_build_current(ctx))
                build['exit_status'] = 1
                with self.assertRaises(acceptance.TestFailure):
                    acceptance.test_native_build_current(ctx)
                build['exit_status'] = 0
                build['binary_sha256'] = 'wrong'
                with self.assertRaises(acceptance.TestBlocked):
                    acceptance.test_native_build_current(ctx)

    def test_tui_fixture_detects_selection_and_rejects_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good = root / 'good.py'
            good.write_text('#!/usr/bin/env python3\nimport time\nprint("Sign in with ChatGPT\\nProvide your own API key", flush=True)\ntime.sleep(30)\n', encoding='utf-8')
            good.chmod(0o700)
            bad = root / 'bad.py'
            bad.write_text('#!/usr/bin/env python3\nprint("unrelated output", flush=True)\n', encoding='utf-8')
            bad.chmod(0o700)
            ctx = acceptance.Context('current')
            with patch.object(acceptance, 'TMP_DIR', root), patch.object(acceptance, 'BINARY', good):
                self.assertIn('authentication selection', acceptance.test_tui_auth_screen_current(ctx))
            with patch.object(acceptance, 'TMP_DIR', root), patch.object(acceptance, 'BINARY', bad):
                with self.assertRaises(acceptance.TestFailure):
                    acceptance.test_tui_auth_screen_current(ctx)

    def test_missing_prompt_tty_fixture_requires_guidance(self):
        diagnostics = ["unexpected argument", "invalid value", "required arguments",
                       "unexpected argument", "no prompt provided", "no prompt provided via stdin"]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = root / 'tty_fixture.py'
            fixture.write_text('#!/usr/bin/env python3\nimport sys\n'
                               'print("No prompt provided.", flush=True)\n'
                               'sys.exit(1)\n', encoding='utf-8')
            fixture.chmod(0o700)
            ctx = acceptance.Context('current')
            responses = iter(subprocess.CompletedProcess([], 2 if n < 4 else 1, diagnostic)
                             for n, diagnostic in enumerate(diagnostics))
            with patch.object(acceptance, 'TMP_DIR', root), \
                 patch.object(acceptance, 'BINARY', fixture), \
                 patch.object(acceptance, 'run_cli', side_effect=lambda *_args, **_kwargs: next(responses)):
                self.assertIn('interactive TTY', acceptance.test_argument_validation_current(ctx))
            fixture.write_text('#!/usr/bin/env python3\nimport sys\n'
                               'print("unrelated output", flush=True)\nsys.exit(1)\n', encoding='utf-8')
            responses = iter(subprocess.CompletedProcess([], 2 if n < 4 else 1, diagnostic)
                             for n, diagnostic in enumerate(diagnostics))
            with patch.object(acceptance, 'TMP_DIR', root), \
                 patch.object(acceptance, 'BINARY', fixture), \
                 patch.object(acceptance, 'run_cli', side_effect=lambda *_args, **_kwargs: next(responses)):
                with self.assertRaises(acceptance.TestFailure):
                    acceptance.test_argument_validation_current(ctx)

    def test_prompt_routing_fixture_rejects_wrong_user_text(self):
        class WrongPromptContext(acceptance.Context):
            def command(self, argv, *, cwd, env, timeout, stdin_text):
                provider = argv[argv.index('-c') + 1]
                base_url = re.search(r'base_url = "([^"]+)"', provider).group(1)
                body = json.dumps({'input': [{'type': 'message', 'role': 'user',
                                               'content': [{'type': 'input_text',
                                                            'text': 'wrong-prompt-marker'}]}]}).encode()
                request = urllib.request.Request(base_url + '/responses', data=body,
                                                 headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=3) as response:
                    response.read()
                return subprocess.CompletedProcess(argv, 0, '')

        with tempfile.TemporaryDirectory() as folder:
            ctx = WrongPromptContext('current')
            with patch.object(acceptance, 'TMP_DIR', Path(folder)):
                with self.assertRaises(acceptance.TestFailure):
                    acceptance.test_prompt_routing_current(ctx)

    def test_dashboard_has_seventeen_scenarios(self):
        state = self.all_mandatory_passed()
        rows = acceptance.scenario_dashboard(state, acceptance.evaluate_acceptance(state, 'current'))
        self.assertEqual(17, len(rows))
        self.assertEqual(['U01', 'U02', 'U03', 'U04', 'U05', 'U06', 'U07'],
                         [row['id'] for row in rows[:7]])
        self.assertEqual('PREVIOUSLY ACCEPTED', rows[4]['status'])

    def test_report_formats_share_acceptance_result(self):
        state = self.all_mandatory_passed()
        counts = {'executed': 0, 'cached': 12, 'held': 0}
        env = {'platform': 'Ubuntu', 'machine': 'aarch64', 'source_sha256': 'a',
               'binary_sha256': 'b', 'apparmor_userns': '1'}
        evaluation = acceptance.evaluate_acceptance(state, 'current')
        markdown = acceptance.report(state, env, 'current', counts, evaluation)
        payload = acceptance.report_payload(state, env, 'current', counts, True, evaluation)
        terminal = acceptance.terminal_summary(evaluation, counts)
        self.assertEqual(evaluation, json.loads(json.dumps(payload))['acceptance'])
        self.assertEqual(17, len(payload['scenarios']))
        self.assertEqual([], payload['builds'])
        self.assertIn('**Automated mandatory gate: PASS**', markdown)
        self.assertIn('**U01 overall: ACCEPTED**', markdown)
        self.assertIn('Acceptance-owner-approved replacement', markdown)
        self.assertIn('Outstanding mandatory U01 checks: 0', markdown)
        self.assertIn('Automated mandatory gate: PASS (0 outstanding)', terminal)
        self.assertIn('U01: ACCEPTED', terminal)

    def test_report_mode_writes_consistent_outputs_without_running_checks(self):
        state = self.all_mandatory_passed()
        env = {'platform': 'Ubuntu', 'machine': 'aarch64', 'source_sha256': 'a',
               'binary_sha256': 'b', 'apparmor_userns': '1'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path = root / 'state.json'
            acceptance.atomic_json(state_path, state)
            output = io.StringIO()
            with patch.object(acceptance, 'STATE_FILE', state_path), \
                 patch.object(acceptance, 'STATE_DIR', root), \
                 patch.object(acceptance, 'TMP_DIR', root / 'tmp'), \
                 patch.object(acceptance, 'REPORT_DIR', root / 'reports'), \
                 patch.object(acceptance, 'fingerprint', return_value=(env, 'current')), \
                 patch.object(acceptance, 'source_digest', return_value='a'), \
                 patch.object(sys, 'argv', ['runner.py', '--mode', 'report']), \
                 redirect_stdout(output):
                self.assertEqual(0, acceptance.main())
            markdown = (root / 'reports' / 'latest-summary.md').read_text(encoding='utf-8')
            payload = json.loads((root / 'reports' / 'latest-results.json').read_text(encoding='utf-8'))
            self.assertEqual('PASS', payload['acceptance']['automated_mandatory_gate'])
            self.assertEqual('ACCEPTED', payload['acceptance']['full_u01'])
            self.assertIn('**Automated mandatory gate: PASS**', markdown)
            self.assertIn('**U01 overall: ACCEPTED**', markdown)
            self.assertIn('Automated mandatory gate: PASS (0 outstanding)', output.getvalue())
            self.assertIn('U01: ACCEPTED', output.getvalue())

    def test_cache_reuses_valid_pass_and_invalidates_changed_definitions(self):
        test = next(t for t in acceptance.QUICK_TESTS if t.test_id == 'u01_default_bubblewrap')
        result = self.passed_result(test)
        self.assertEqual('CACHED', acceptance.cache_disposition(result, test, 'current', False))
        self.assertEqual('RUN', acceptance.cache_disposition(result, test, 'current', True))
        self.assertEqual('RUN', acceptance.cache_disposition(result, test, 'changed', False))
        result['test_revision'] += 1
        self.assertEqual('RUN', acceptance.cache_disposition(result, test, 'current', False))
        result['test_revision'] -= 1
        result['status'] = 'FAIL'
        self.assertEqual('HELD', acceptance.cache_disposition(result, test, 'current', False))
        self.assertEqual('RUN', acceptance.cache_disposition(result, test, 'current', True))
        result['status'] = 'PASS'
        result['provenance'] = 'prior conversation'
        self.assertEqual('RUN', acceptance.cache_disposition(result, test, 'current', False))

    def test_rerun_logs_preserve_prior_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(acceptance, 'LOG_DIR', Path(folder)):
                first = acceptance.write_log('u01_default_bubblewrap', ['first'], 'FAIL', 'old failure')
                second = acceptance.write_log('u01_default_bubblewrap', ['second'], 'PASS', 'new pass')
            self.assertNotEqual(first, second)
            self.assertIn('old failure', Path(first).read_text(encoding='utf-8'))
            self.assertIn('new pass', Path(second).read_text(encoding='utf-8'))

    def test_source_integrity_failure_blocks_automated_gate(self):
        evaluation = acceptance.evaluate_acceptance(self.all_mandatory_passed(), 'current', False)
        self.assertEqual('PENDING', evaluation['automated_mandatory_gate'])
        self.assertFalse(evaluation['source_integrity_ok'])

    def test_readonly_security_probe_fails_if_write_is_permitted(self):
        class ControlContext:
            def command(self, argv, *, cwd):
                return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)

        def permitted_write(_ctx, cwd, _script):
            (cwd / 'probe.txt').write_text('WRITE\n', encoding='utf-8')
            return subprocess.CompletedProcess([], 0, 'PROBE_STARTED\n')

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(acceptance, 'TMP_DIR', Path(folder)):
                with patch.object(acceptance, 'bubblewrap_shell', side_effect=permitted_write):
                    with self.assertRaises(acceptance.TestFailure):
                        acceptance.test_bubblewrap_readonly(ControlContext())

    def test_test_definitions_are_unique_and_discoverable(self):
        ids = [test.test_id for test in acceptance.ALL_TESTS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('u01_default_bubblewrap', ids)
        self.assertIn('u01_default_bubblewrap_ipv6', ids)


if __name__ == '__main__':
    unittest.main(verbosity=2)
