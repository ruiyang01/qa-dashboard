#!/usr/bin/env python3
"""
Playwright Test Results Reporter

This script parses Playwright JSON report and sends results to QA Dashboard.

Usage:
    # After running playwright tests with JSON reporter:
    npx playwright test --reporter=json > results.json
    
    # Send to dashboard:
    python reporter.py results.json --project my-app --branch main
    
    # Or pipe directly:
    npx playwright test --reporter=json | python reporter.py - --project my-app
"""

import json
import sys
import argparse
import requests
from datetime import datetime
from typing import List, Dict, Any


def parse_playwright_report(report_data: Dict[Any, Any]) -> List[Dict[str, Any]]:
    """Parse Playwright JSON report into our format"""
    results = []
    
    for suite in report_data.get('suites', []):
        results.extend(parse_suite(suite))
    
    return results


def parse_suite(suite: Dict[Any, Any], parent_title: str = '') -> List[Dict[str, Any]]:
    """Recursively parse test suites"""
    results = []
    suite_title = f"{parent_title} > {suite.get('title', '')}" if parent_title else suite.get('title', '')
    
    # Parse specs (individual tests)
    for spec in suite.get('specs', []):
        for test in spec.get('tests', []):
            result = parse_test(spec, test, suite_title)
            results.append(result)
    
    # Parse nested suites
    for child_suite in suite.get('suites', []):
        results.extend(parse_suite(child_suite, suite_title))
    
    return results


def parse_test(spec: Dict[Any, Any], test: Dict[Any, Any], suite_title: str) -> Dict[str, Any]:
    """Parse individual test result"""
    
    # Get the last result (after retries)
    test_results = test.get('results', [])
    last_result = test_results[-1] if test_results else {}
    
    # Determine status
    status = last_result.get('status', 'skipped')
    if status == 'passed':
        status = 'passed'
    elif status == 'failed':
        status = 'failed'
    elif status == 'timedOut':
        status = 'failed'
    elif status == 'skipped':
        status = 'skipped'
    
    # Check if flaky (passed after retry)
    retry_count = len(test_results) - 1
    if retry_count > 0 and status == 'passed':
        status = 'flaky'
    
    # Extract error info
    error_message = None
    stack_trace = None
    if last_result.get('error'):
        error = last_result['error']
        error_message = error.get('message', '')
        stack_trace = error.get('stack', '')
    
    # Get browser from project name
    browser = None
    project_name = test.get('projectName', '')
    if 'chromium' in project_name.lower():
        browser = 'chromium'
    elif 'firefox' in project_name.lower():
        browser = 'firefox'
    elif 'webkit' in project_name.lower():
        browser = 'webkit'
    
    return {
        'name': f"{suite_title} > {spec.get('title', 'Unknown')}",
        'status': status,
        'duration_ms': int(last_result.get('duration', 0)),
        'test_type': 'playwright',
        'suite': suite_title,
        'error_message': error_message,
        'stack_trace': stack_trace,
        'retry_count': retry_count,
        'browser': browser,
        'tags': test.get('annotations', [])
    }


def send_to_dashboard(
    api_url: str,
    project: str,
    branch: str,
    results: List[Dict[str, Any]],
    commit_sha: str = None,
    triggered_by: str = 'ci',
    environment: str = 'staging'
) -> Dict[str, Any]:
    """Send test results to QA Dashboard API"""
    
    payload = {
        'project': project,
        'branch': branch,
        'commit_sha': commit_sha,
        'triggered_by': triggered_by,
        'environment': environment,
        'results': results,
        'started_at': datetime.now().isoformat(),
        'finished_at': datetime.now().isoformat()
    }
    
    response = requests.post(
        f"{api_url}/api/v1/runs",
        json=payload,
        headers={'Content-Type': 'application/json'}
    )
    
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description='Send Playwright results to QA Dashboard')
    parser.add_argument('report_file', help='Path to Playwright JSON report (use - for stdin)')
    parser.add_argument('--api-url', default='http://localhost:3000', help='QA Dashboard API URL')
    parser.add_argument('--project', required=True, help='Project name')
    parser.add_argument('--branch', default='main', help='Git branch')
    parser.add_argument('--commit', help='Git commit SHA')
    parser.add_argument('--triggered-by', default='ci', help='Who triggered the run')
    parser.add_argument('--environment', default='staging', help='Test environment')
    parser.add_argument('--dry-run', action='store_true', help='Parse only, do not send')
    
    args = parser.parse_args()
    
    # Read report
    if args.report_file == '-':
        report_data = json.load(sys.stdin)
    else:
        with open(args.report_file, 'r') as f:
            report_data = json.load(f)
    
    # Parse results
    results = parse_playwright_report(report_data)
    
    print(f"📊 Parsed {len(results)} test results")
    
    # Summary
    passed = sum(1 for r in results if r['status'] == 'passed')
    failed = sum(1 for r in results if r['status'] == 'failed')
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    flaky = sum(1 for r in results if r['status'] == 'flaky')
    
    print(f"   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    print(f"   ⏭️  Skipped: {skipped}")
    print(f"   ⚠️  Flaky: {flaky}")
    
    if args.dry_run:
        print("\n🔍 Dry run - not sending to API")
        print(json.dumps(results[:3], indent=2))  # Show first 3
        return
    
    # Send to dashboard
    try:
        response = send_to_dashboard(
            api_url=args.api_url,
            project=args.project,
            branch=args.branch,
            results=results,
            commit_sha=args.commit,
            triggered_by=args.triggered_by,
            environment=args.environment
        )
        
        print(f"\n✅ Results sent successfully!")
        print(f"   Run ID: {response.get('run_id')}")
        print(f"   Pass Rate: {response.get('pass_rate'):.1f}%")
        print(f"   View at: {args.api_url}")
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Failed to send results: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
