#!/usr/bin/env python3
"""
Postman/Newman API Test Results Reporter

This script parses Newman JSON report and sends results to QA Dashboard.

Usage:
    # Run Newman with JSON reporter:
    newman run collection.json -r json --reporter-json-export results.json
    
    # Send to dashboard:
    python api_reporter.py results.json --project my-api --branch main
"""

import json
import sys
import argparse
import requests
from datetime import datetime
from typing import List, Dict, Any


def parse_newman_report(report_data: Dict[Any, Any]) -> List[Dict[str, Any]]:
    """Parse Newman JSON report into our format"""
    results = []
    
    run = report_data.get('run', {})
    executions = run.get('executions', [])
    
    for execution in executions:
        item = execution.get('item', {})
        
        # Get assertions
        assertions = execution.get('assertions', [])
        
        # If no assertions, treat request success/failure as the test
        if not assertions:
            response = execution.get('response', {})
            request_error = execution.get('requestError')
            
            results.append({
                'name': item.get('name', 'Unknown Request'),
                'status': 'failed' if request_error else 'passed',
                'duration_ms': response.get('responseTime', 0),
                'test_type': 'api',
                'suite': get_folder_path(item),
                'error_message': str(request_error) if request_error else None,
                'stack_trace': None,
                'retry_count': 0,
                'browser': None,
                'tags': ['api', 'postman']
            })
        else:
            # Each assertion is a test
            for assertion in assertions:
                error = assertion.get('error')
                
                results.append({
                    'name': f"{item.get('name', 'Unknown')} - {assertion.get('assertion', 'assertion')}",
                    'status': 'failed' if error else 'passed',
                    'duration_ms': execution.get('response', {}).get('responseTime', 0),
                    'test_type': 'api',
                    'suite': get_folder_path(item),
                    'error_message': error.get('message') if error else None,
                    'stack_trace': error.get('stack') if error else None,
                    'retry_count': 0,
                    'browser': None,
                    'tags': ['api', 'postman']
                })
    
    return results


def get_folder_path(item: Dict[Any, Any]) -> str:
    """Get the folder path for an item"""
    # Newman doesn't include folder path directly, use item name
    return item.get('name', 'default')


def parse_pytest_json(report_data: Dict[Any, Any]) -> List[Dict[str, Any]]:
    """Parse pytest JSON report (pytest-json-report plugin)"""
    results = []
    
    tests = report_data.get('tests', [])
    
    for test in tests:
        outcome = test.get('outcome', 'passed')
        
        status = 'passed'
        if outcome == 'failed':
            status = 'failed'
        elif outcome == 'skipped':
            status = 'skipped'
        elif outcome == 'xfailed':
            status = 'flaky'
        
        # Extract error info
        error_message = None
        stack_trace = None
        
        call = test.get('call', {})
        if call.get('crash'):
            crash = call['crash']
            error_message = crash.get('message', '')
            stack_trace = call.get('traceback', '')
        
        results.append({
            'name': test.get('nodeid', 'Unknown'),
            'status': status,
            'duration_ms': int(test.get('duration', 0) * 1000),
            'test_type': 'api',
            'suite': test.get('nodeid', '').split('::')[0],
            'error_message': error_message,
            'stack_trace': stack_trace,
            'retry_count': 0,
            'browser': None,
            'tags': test.get('keywords', [])
        })
    
    return results


def detect_report_type(report_data: Dict[Any, Any]) -> str:
    """Detect the type of test report"""
    if 'run' in report_data and 'executions' in report_data.get('run', {}):
        return 'newman'
    elif 'tests' in report_data and 'created' in report_data:
        return 'pytest'
    else:
        return 'unknown'


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
    parser = argparse.ArgumentParser(description='Send API test results to QA Dashboard')
    parser.add_argument('report_file', help='Path to JSON report (use - for stdin)')
    parser.add_argument('--api-url', default='http://localhost:3000', help='QA Dashboard API URL')
    parser.add_argument('--project', required=True, help='Project name')
    parser.add_argument('--branch', default='main', help='Git branch')
    parser.add_argument('--commit', help='Git commit SHA')
    parser.add_argument('--triggered-by', default='ci', help='Who triggered the run')
    parser.add_argument('--environment', default='staging', help='Test environment')
    parser.add_argument('--format', choices=['newman', 'pytest', 'auto'], default='auto',
                        help='Report format')
    parser.add_argument('--dry-run', action='store_true', help='Parse only, do not send')
    
    args = parser.parse_args()
    
    # Read report
    if args.report_file == '-':
        report_data = json.load(sys.stdin)
    else:
        with open(args.report_file, 'r') as f:
            report_data = json.load(f)
    
    # Detect or use specified format
    report_type = args.format
    if report_type == 'auto':
        report_type = detect_report_type(report_data)
        print(f"📋 Detected report type: {report_type}")
    
    # Parse results
    if report_type == 'newman':
        results = parse_newman_report(report_data)
    elif report_type == 'pytest':
        results = parse_pytest_json(report_data)
    else:
        print(f"❌ Unknown report format")
        sys.exit(1)
    
    print(f"📊 Parsed {len(results)} test results")
    
    # Summary
    passed = sum(1 for r in results if r['status'] == 'passed')
    failed = sum(1 for r in results if r['status'] == 'failed')
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    
    print(f"   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    print(f"   ⏭️  Skipped: {skipped}")
    
    if args.dry_run:
        print("\n🔍 Dry run - not sending to API")
        print(json.dumps(results[:3], indent=2))
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
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Failed to send results: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
