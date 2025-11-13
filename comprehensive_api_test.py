#!/usr/bin/env python3
"""
Comprehensive API Testing Script for testmcpy API server.
Tests all endpoints with valid and invalid inputs, documenting all failures.
"""

import json
import sys
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import httpx
from datetime import datetime

BASE_URL = "http://localhost:8000"

class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

@dataclass
class TestResult:
    endpoint: str
    method: str
    test_name: str
    passed: bool
    expected_status: int
    actual_status: Optional[int] = None
    error_message: Optional[str] = None
    request_data: Optional[Dict] = None
    response_data: Optional[Any] = None
    severity: Optional[Severity] = None

@dataclass
class TestReport:
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    results: List[TestResult] = field(default_factory=list)
    bugs: List[Dict[str, Any]] = field(default_factory=list)

class APITester:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)
        self.report = TestReport()

    def log_result(self, result: TestResult):
        """Log a test result"""
        self.report.total_tests += 1
        if result.passed:
            self.report.passed_tests += 1
            print(f"✓ {result.method} {result.endpoint} - {result.test_name}")
        else:
            self.report.failed_tests += 1
            print(f"✗ {result.method} {result.endpoint} - {result.test_name}")
            print(f"  Expected: {result.expected_status}, Got: {result.actual_status}")
            if result.error_message:
                print(f"  Error: {result.error_message}")
        self.report.results.append(result)

    def add_bug(self, endpoint: str, method: str, severity: Severity,
                description: str, details: Dict[str, Any]):
        """Add a bug to the report"""
        bug = {
            "endpoint": f"{method} {endpoint}",
            "severity": severity.value,
            "description": description,
            "details": details
        }
        self.report.bugs.append(bug)

    def test_endpoint(self, method: str, endpoint: str, test_name: str,
                     expected_status: int, data: Optional[Dict] = None,
                     params: Optional[Dict] = None, severity: Optional[Severity] = None):
        """Generic endpoint test"""
        url = f"{self.base_url}{endpoint}"
        result = TestResult(
            endpoint=endpoint,
            method=method,
            test_name=test_name,
            passed=False,
            expected_status=expected_status,
            request_data=data or params,
            severity=severity
        )

        try:
            if method == "GET":
                response = self.client.get(url, params=params)
            elif method == "POST":
                response = self.client.post(url, json=data)
            elif method == "PUT":
                response = self.client.put(url, json=data)
            elif method == "DELETE":
                response = self.client.delete(url)
            else:
                raise ValueError(f"Unsupported method: {method}")

            result.actual_status = response.status_code

            # Try to parse JSON response
            try:
                result.response_data = response.json()
            except:
                result.response_data = response.text

            result.passed = (response.status_code == expected_status)

            # Log bug if failed and severity provided
            if not result.passed and severity:
                self.add_bug(
                    endpoint=endpoint,
                    method=method,
                    severity=severity,
                    description=f"{test_name} failed",
                    details={
                        "expected_status": expected_status,
                        "actual_status": response.status_code,
                        "request": data or params,
                        "response": result.response_data
                    }
                )

        except Exception as e:
            result.actual_status = None
            result.error_message = str(e)
            if severity:
                self.add_bug(
                    endpoint=endpoint,
                    method=method,
                    severity=Severity.CRITICAL,
                    description=f"{test_name} - Exception occurred",
                    details={
                        "exception": str(e),
                        "request": data or params
                    }
                )

        self.log_result(result)
        return result

    def test_health_endpoints(self):
        """Test health and status endpoints"""
        print("\n=== Testing Health & Status Endpoints ===")

        # Test /api/health
        self.test_endpoint("GET", "/api/health", "Health check", 200, severity=Severity.CRITICAL)

        # Test /api/config
        self.test_endpoint("GET", "/api/config", "Get configuration", 200, severity=Severity.HIGH)

        # Test root endpoint
        self.test_endpoint("GET", "/", "Root endpoint", 200, severity=Severity.LOW)

    def test_profile_endpoints(self):
        """Test MCP profile endpoints"""
        print("\n=== Testing Profile Endpoints ===")

        # List profiles
        result = self.test_endpoint("GET", "/api/mcp/profiles", "List profiles", 200, severity=Severity.CRITICAL)
        profiles = result.response_data if result.passed else {}

        # Test with real profile from config
        profile_ids = ["local-dev", "sandbox", "staging", "prod"]

        for profile_id in profile_ids:
            # Export profile
            self.test_endpoint("GET", f"/api/mcp/profiles/{profile_id}/export",
                             f"Export profile {profile_id}", 200, severity=Severity.MEDIUM)

            # Set as default
            self.test_endpoint("PUT", f"/api/mcp/profiles/default/{profile_id}",
                             f"Set {profile_id} as default", 200, severity=Severity.MEDIUM)

            # Test connection (mcp_index 0)
            self.test_endpoint("POST", f"/api/mcp/profiles/{profile_id}/test-connection/0",
                             f"Test connection for {profile_id}", 200, severity=Severity.HIGH)

        # Test non-existent profile
        self.test_endpoint("GET", "/api/mcp/profiles/nonexistent/export",
                         "Export non-existent profile", 404, severity=Severity.MEDIUM)

        # Test invalid mcp_index
        self.test_endpoint("POST", "/api/mcp/profiles/local-dev/test-connection/999",
                         "Test connection with invalid index", 404, severity=Severity.MEDIUM)

        # Test create profile - valid
        create_data = {
            "profile_id": "test-profile",
            "name": "Test Profile",
            "description": "A test profile",
            "mcps": []
        }
        self.test_endpoint("POST", "/api/mcp/profiles", "Create valid profile",
                         200, data=create_data, severity=Severity.HIGH)

        # Test create profile - missing required fields
        self.test_endpoint("POST", "/api/mcp/profiles", "Create profile missing fields",
                         422, data={"profile_id": "test"}, severity=Severity.MEDIUM)

        # Test create profile - empty profile_id
        self.test_endpoint("POST", "/api/mcp/profiles", "Create profile empty id",
                         422, data={"profile_id": "", "name": "Test"}, severity=Severity.MEDIUM)

        # Test update profile
        update_data = {
            "name": "Updated Test Profile",
            "description": "Updated description"
        }
        self.test_endpoint("PUT", "/api/mcp/profiles/test-profile", "Update profile",
                         200, data=update_data, severity=Severity.HIGH)

        # Test update non-existent profile
        self.test_endpoint("PUT", "/api/mcp/profiles/nonexistent", "Update non-existent profile",
                         404, data=update_data, severity=Severity.MEDIUM)

        # Test duplicate profile
        self.test_endpoint("POST", "/api/mcp/profiles/test-profile/duplicate",
                         "Duplicate profile", 200, severity=Severity.MEDIUM)

        # Test duplicate non-existent profile
        self.test_endpoint("POST", "/api/mcp/profiles/nonexistent/duplicate",
                         "Duplicate non-existent profile", 404, severity=Severity.MEDIUM)

        # Test delete profile
        self.test_endpoint("DELETE", "/api/mcp/profiles/test-profile", "Delete profile",
                         200, severity=Severity.HIGH)

        # Test delete non-existent profile
        self.test_endpoint("DELETE", "/api/mcp/profiles/nonexistent", "Delete non-existent profile",
                         404, severity=Severity.MEDIUM)

    def test_mcp_management_endpoints(self):
        """Test MCP server management within profiles"""
        print("\n=== Testing MCP Management Endpoints ===")

        # Create a test profile first
        create_data = {
            "profile_id": "test-mcp-profile",
            "name": "Test MCP Profile",
            "description": "For testing MCP operations",
            "mcps": []
        }
        self.test_endpoint("POST", "/api/mcp/profiles", "Create profile for MCP tests",
                         200, data=create_data, severity=Severity.HIGH)

        # Add MCP to profile - valid
        mcp_data = {
            "name": "Test MCP",
            "mcp_url": "http://localhost:8080/mcp",
            "auth": {"type": "none"}
        }
        self.test_endpoint("POST", "/api/mcp/profiles/test-mcp-profile/mcps",
                         "Add MCP to profile", 200, data=mcp_data, severity=Severity.HIGH)

        # Add MCP - missing required fields
        self.test_endpoint("POST", "/api/mcp/profiles/test-mcp-profile/mcps",
                         "Add MCP missing fields", 422, data={"name": "Test"},
                         severity=Severity.MEDIUM)

        # Add MCP - invalid URL
        invalid_mcp = {
            "name": "Invalid MCP",
            "mcp_url": "not-a-url",
            "auth": {"type": "none"}
        }
        self.test_endpoint("POST", "/api/mcp/profiles/test-mcp-profile/mcps",
                         "Add MCP with invalid URL", 422, data=invalid_mcp,
                         severity=Severity.MEDIUM)

        # Add MCP to non-existent profile
        self.test_endpoint("POST", "/api/mcp/profiles/nonexistent/mcps",
                         "Add MCP to non-existent profile", 404, data=mcp_data,
                         severity=Severity.MEDIUM)

        # Update MCP in profile
        update_mcp = {
            "name": "Updated Test MCP",
            "mcp_url": "http://localhost:9090/mcp"
        }
        self.test_endpoint("PUT", "/api/mcp/profiles/test-mcp-profile/mcps/0",
                         "Update MCP in profile", 200, data=update_mcp,
                         severity=Severity.HIGH)

        # Update MCP - invalid index
        self.test_endpoint("PUT", "/api/mcp/profiles/test-mcp-profile/mcps/999",
                         "Update MCP invalid index", 404, data=update_mcp,
                         severity=Severity.MEDIUM)

        # Update MCP - negative index
        self.test_endpoint("PUT", "/api/mcp/profiles/test-mcp-profile/mcps/-1",
                         "Update MCP negative index", 404, data=update_mcp,
                         severity=Severity.MEDIUM)

        # Add another MCP for reorder test
        mcp_data2 = {
            "name": "Second MCP",
            "mcp_url": "http://localhost:8081/mcp",
            "auth": {"type": "none"}
        }
        self.test_endpoint("POST", "/api/mcp/profiles/test-mcp-profile/mcps",
                         "Add second MCP", 200, data=mcp_data2, severity=Severity.HIGH)

        # Reorder MCPs
        reorder_data = {"new_order": [1, 0]}
        self.test_endpoint("PUT", "/api/mcp/profiles/test-mcp-profile/mcps/reorder",
                         "Reorder MCPs", 200, data=reorder_data, severity=Severity.MEDIUM)

        # Reorder MCPs - invalid order (wrong length)
        self.test_endpoint("PUT", "/api/mcp/profiles/test-mcp-profile/mcps/reorder",
                         "Reorder MCPs invalid length", 422,
                         data={"new_order": [0]}, severity=Severity.MEDIUM)

        # Reorder MCPs - invalid order (out of bounds)
        self.test_endpoint("PUT", "/api/mcp/profiles/test-mcp-profile/mcps/reorder",
                         "Reorder MCPs out of bounds", 422,
                         data={"new_order": [0, 5]}, severity=Severity.MEDIUM)

        # Delete MCP from profile
        self.test_endpoint("DELETE", "/api/mcp/profiles/test-mcp-profile/mcps/0",
                         "Delete MCP from profile", 200, severity=Severity.HIGH)

        # Delete MCP - invalid index
        self.test_endpoint("DELETE", "/api/mcp/profiles/test-mcp-profile/mcps/999",
                         "Delete MCP invalid index", 404, severity=Severity.MEDIUM)

        # Clean up
        self.test_endpoint("DELETE", "/api/mcp/profiles/test-mcp-profile",
                         "Delete test profile", 200, severity=Severity.HIGH)

    def test_tool_endpoints(self):
        """Test MCP tools, resources, and prompts endpoints"""
        print("\n=== Testing Tool Endpoints ===")

        # List tools
        self.test_endpoint("GET", "/api/mcp/tools", "List all tools", 200, severity=Severity.HIGH)

        # List tools with profiles filter
        self.test_endpoint("GET", "/api/mcp/tools", "List tools with profile filter",
                         200, params={"profiles": ["local-dev"]}, severity=Severity.MEDIUM)

        # List tools with multiple profiles
        self.test_endpoint("GET", "/api/mcp/tools", "List tools with multiple profiles",
                         200, params={"profiles": ["local-dev", "sandbox"]}, severity=Severity.MEDIUM)

        # List tools with non-existent profile
        self.test_endpoint("GET", "/api/mcp/tools", "List tools with non-existent profile",
                         200, params={"profiles": ["nonexistent"]}, severity=Severity.LOW)

        # List resources
        self.test_endpoint("GET", "/api/mcp/resources", "List all resources", 200, severity=Severity.HIGH)

        # List resources with profile filter
        self.test_endpoint("GET", "/api/mcp/resources", "List resources with profile filter",
                         200, params={"profiles": ["local-dev"]}, severity=Severity.MEDIUM)

        # List prompts
        self.test_endpoint("GET", "/api/mcp/prompts", "List all prompts", 200, severity=Severity.HIGH)

        # List prompts with profile filter
        self.test_endpoint("GET", "/api/mcp/prompts", "List prompts with profile filter",
                         200, params={"profiles": ["local-dev"]}, severity=Severity.MEDIUM)

    def test_model_endpoints(self):
        """Test model listing endpoints"""
        print("\n=== Testing Model Endpoints ===")

        # List models
        self.test_endpoint("GET", "/api/models", "List available models", 200, severity=Severity.HIGH)

    def test_chat_endpoint(self):
        """Test chat endpoint"""
        print("\n=== Testing Chat Endpoint ===")

        # Valid chat request
        chat_data = {
            "message": "Hello, what tools are available?",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
            "profile_ids": ["local-dev"]
        }
        self.test_endpoint("POST", "/api/chat", "Valid chat request",
                         200, data=chat_data, severity=Severity.CRITICAL)

        # Chat with missing message
        self.test_endpoint("POST", "/api/chat", "Chat missing message",
                         422, data={"provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
                         severity=Severity.MEDIUM)

        # Chat with missing provider
        self.test_endpoint("POST", "/api/chat", "Chat missing provider",
                         422, data={"message": "Test", "model": "claude-3-5-sonnet-20241022"},
                         severity=Severity.MEDIUM)

        # Chat with empty message
        empty_msg_data = {
            "message": "",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022"
        }
        self.test_endpoint("POST", "/api/chat", "Chat with empty message",
                         422, data=empty_msg_data, severity=Severity.MEDIUM)

        # Chat with invalid provider
        invalid_provider_data = {
            "message": "Test",
            "provider": "invalid-provider",
            "model": "some-model"
        }
        self.test_endpoint("POST", "/api/chat", "Chat with invalid provider",
                         422, data=invalid_provider_data, severity=Severity.MEDIUM)

        # Chat with non-existent profile
        nonexist_profile_data = {
            "message": "Test",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
            "profile_ids": ["nonexistent"]
        }
        self.test_endpoint("POST", "/api/chat", "Chat with non-existent profile",
                         200, data=nonexist_profile_data, severity=Severity.LOW)

    def test_test_file_endpoints(self):
        """Test test file management endpoints"""
        print("\n=== Testing Test File Endpoints ===")

        # List tests
        self.test_endpoint("GET", "/api/tests", "List test files", 200, severity=Severity.HIGH)

        # Create test file
        test_file_data = {
            "name": "api_test_suite",
            "description": "Comprehensive API tests",
            "test_cases": [
                {
                    "name": "Test Case 1",
                    "description": "A test case",
                    "profile": "local-dev",
                    "llm_provider": "anthropic",
                    "llm_model": "claude-3-5-sonnet-20241022",
                    "prompt": "Test prompt",
                    "expectations": ["Should work"]
                }
            ]
        }
        result = self.test_endpoint("POST", "/api/tests", "Create test file",
                                   200, data=test_file_data, severity=Severity.HIGH)

        # Create test file - missing required fields
        self.test_endpoint("POST", "/api/tests", "Create test file missing fields",
                         422, data={"name": "test"}, severity=Severity.MEDIUM)

        # Create test file - empty name
        self.test_endpoint("POST", "/api/tests", "Create test file empty name",
                         422, data={**test_file_data, "name": ""}, severity=Severity.MEDIUM)

        # Get test file
        self.test_endpoint("GET", "/api/tests/api_test_suite", "Get test file",
                         200, severity=Severity.HIGH)

        # Get non-existent test file
        self.test_endpoint("GET", "/api/tests/nonexistent", "Get non-existent test file",
                         404, severity=Severity.MEDIUM)

        # Update test file
        update_test_data = {
            **test_file_data,
            "description": "Updated description"
        }
        self.test_endpoint("PUT", "/api/tests/api_test_suite", "Update test file",
                         200, data=update_test_data, severity=Severity.HIGH)

        # Update non-existent test file
        self.test_endpoint("PUT", "/api/tests/nonexistent", "Update non-existent test file",
                         404, data=update_test_data, severity=Severity.MEDIUM)

        # Delete test file
        self.test_endpoint("DELETE", "/api/tests/api_test_suite", "Delete test file",
                         200, severity=Severity.HIGH)

        # Delete non-existent test file
        self.test_endpoint("DELETE", "/api/tests/nonexistent", "Delete non-existent test file",
                         404, severity=Severity.MEDIUM)

    def test_test_execution_endpoints(self):
        """Test test execution endpoints"""
        print("\n=== Testing Test Execution Endpoints ===")

        # First create a test file
        test_file_data = {
            "name": "execution_test",
            "description": "Test for execution",
            "test_cases": [
                {
                    "name": "Simple Test",
                    "description": "A simple test",
                    "profile": "local-dev",
                    "llm_provider": "anthropic",
                    "llm_model": "claude-3-5-sonnet-20241022",
                    "prompt": "What is 2+2?",
                    "expectations": ["Should calculate"]
                }
            ]
        }
        self.test_endpoint("POST", "/api/tests", "Create test for execution",
                         200, data=test_file_data, severity=Severity.HIGH)

        # Run test
        run_config = {
            "profile": "local-dev",
            "llm_provider": "anthropic",
            "llm_model": "claude-3-5-sonnet-20241022"
        }
        self.test_endpoint("POST", "/api/tests/execution_test/run", "Run test",
                         200, data=run_config, severity=Severity.CRITICAL)

        # Run non-existent test
        self.test_endpoint("POST", "/api/tests/nonexistent/run", "Run non-existent test",
                         404, data=run_config, severity=Severity.MEDIUM)

        # Run test with missing config
        self.test_endpoint("POST", "/api/tests/execution_test/run", "Run test missing config",
                         422, data={}, severity=Severity.MEDIUM)

        # Run specific test case
        self.test_endpoint("POST", "/api/tests/execution_test/cases/0/run",
                         "Run specific test case", 200, data=run_config, severity=Severity.HIGH)

        # Run test case - invalid index
        self.test_endpoint("POST", "/api/tests/execution_test/cases/999/run",
                         "Run test case invalid index", 404, data=run_config,
                         severity=Severity.MEDIUM)

        # Clean up
        self.test_endpoint("DELETE", "/api/tests/execution_test", "Delete execution test",
                         200, severity=Severity.HIGH)

    def test_report_endpoints(self):
        """Test report endpoints"""
        print("\n=== Testing Report Endpoints ===")

        # List reports
        self.test_endpoint("GET", "/api/reports", "List reports", 200, severity=Severity.HIGH)

        # Get report (may not exist yet)
        self.test_endpoint("GET", "/api/reports/nonexistent", "Get non-existent report",
                         404, severity=Severity.LOW)

    def test_config_endpoints(self):
        """Test configuration endpoints"""
        print("\n=== Testing Config Endpoints ===")

        # Create MCP config
        self.test_endpoint("POST", "/api/mcp/profiles/create-config",
                         "Create MCP config", 200, severity=Severity.MEDIUM)

    def test_edge_cases(self):
        """Test edge cases and special scenarios"""
        print("\n=== Testing Edge Cases ===")

        # Very long strings
        long_name = "x" * 10000
        long_data = {
            "profile_id": "test-long",
            "name": long_name,
            "description": "Test",
            "mcps": []
        }
        self.test_endpoint("POST", "/api/mcp/profiles", "Create profile with very long name",
                         422, data=long_data, severity=Severity.LOW)

        # Special characters in profile_id
        special_data = {
            "profile_id": "test/../../../etc/passwd",
            "name": "Malicious",
            "description": "Path traversal attempt",
            "mcps": []
        }
        self.test_endpoint("POST", "/api/mcp/profiles", "Create profile with path traversal",
                         422, data=special_data, severity=Severity.HIGH)

        # SQL injection attempt
        sql_data = {
            "profile_id": "test'; DROP TABLE profiles--",
            "name": "SQL Injection",
            "description": "Test",
            "mcps": []
        }
        self.test_endpoint("POST", "/api/mcp/profiles", "Create profile with SQL injection",
                         422, data=sql_data, severity=Severity.MEDIUM)

        # Null bytes
        null_data = {
            "profile_id": "test\x00null",
            "name": "Null byte",
            "description": "Test",
            "mcps": []
        }
        self.test_endpoint("POST", "/api/mcp/profiles", "Create profile with null byte",
                         422, data=null_data, severity=Severity.MEDIUM)

        # Unicode characters
        unicode_data = {
            "profile_id": "test-unicode-😀-🎉",
            "name": "Unicode 测试 тест",
            "description": "Testing unicode support",
            "mcps": []
        }
        result = self.test_endpoint("POST", "/api/mcp/profiles", "Create profile with unicode",
                                   200, data=unicode_data, severity=Severity.LOW)
        if result.passed:
            # Clean up if created
            self.test_endpoint("DELETE", f"/api/mcp/profiles/{unicode_data['profile_id']}",
                             "Delete unicode profile", 200, severity=Severity.LOW)

    def generate_report(self) -> str:
        """Generate comprehensive test report"""
        report = []
        report.append("\n" + "="*80)
        report.append("COMPREHENSIVE API TEST REPORT")
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append("="*80)

        report.append(f"\n## Summary")
        report.append(f"Total Tests: {self.report.total_tests}")
        report.append(f"Passed: {self.report.passed_tests}")
        report.append(f"Failed: {self.report.failed_tests}")
        report.append(f"Pass Rate: {(self.report.passed_tests/self.report.total_tests*100):.2f}%")

        # Group bugs by severity
        bugs_by_severity = {
            Severity.CRITICAL: [],
            Severity.HIGH: [],
            Severity.MEDIUM: [],
            Severity.LOW: []
        }

        for bug in self.report.bugs:
            severity = Severity(bug['severity'])
            bugs_by_severity[severity].append(bug)

        report.append(f"\n## Bugs Found: {len(self.report.bugs)}")
        for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
            bugs = bugs_by_severity[severity]
            if bugs:
                report.append(f"\n### {severity.value} ({len(bugs)})")
                for i, bug in enumerate(bugs, 1):
                    report.append(f"\n{i}. {bug['endpoint']}")
                    report.append(f"   Description: {bug['description']}")
                    report.append(f"   Details:")
                    for key, value in bug['details'].items():
                        report.append(f"     - {key}: {value}")

        # Detailed test results
        report.append(f"\n## Detailed Test Results")

        failed_results = [r for r in self.report.results if not r.passed]
        if failed_results:
            report.append(f"\n### Failed Tests ({len(failed_results)})")
            for result in failed_results:
                report.append(f"\n- {result.method} {result.endpoint} - {result.test_name}")
                report.append(f"  Expected: {result.expected_status}, Got: {result.actual_status}")
                if result.error_message:
                    report.append(f"  Error: {result.error_message}")
                if result.request_data:
                    report.append(f"  Request: {json.dumps(result.request_data, indent=2)}")
                if result.response_data:
                    response_str = json.dumps(result.response_data, indent=2) if isinstance(result.response_data, dict) else str(result.response_data)
                    report.append(f"  Response: {response_str[:500]}")  # Truncate long responses

        report.append("\n" + "="*80)
        report.append("END OF REPORT")
        report.append("="*80)

        return "\n".join(report)

    def run_all_tests(self):
        """Run all test suites"""
        print("Starting comprehensive API testing...")
        print(f"Base URL: {self.base_url}")

        try:
            self.test_health_endpoints()
            self.test_profile_endpoints()
            self.test_mcp_management_endpoints()
            self.test_tool_endpoints()
            self.test_model_endpoints()
            self.test_chat_endpoint()
            self.test_test_file_endpoints()
            self.test_test_execution_endpoints()
            self.test_report_endpoints()
            self.test_config_endpoints()
            self.test_edge_cases()
        except KeyboardInterrupt:
            print("\n\nTesting interrupted by user")
        except Exception as e:
            print(f"\n\nFatal error during testing: {e}")
            import traceback
            traceback.print_exc()

        # Generate and print report
        report = self.generate_report()
        print(report)

        # Save report to file
        report_file = "/Users/amin/github/preset-io/testmcpy/api_test_report.txt"
        with open(report_file, "w") as f:
            f.write(report)
        print(f"\nReport saved to: {report_file}")

        return self.report

if __name__ == "__main__":
    tester = APITester(BASE_URL)
    report = tester.run_all_tests()

    # Exit with error code if tests failed
    sys.exit(0 if report.failed_tests == 0 else 1)
