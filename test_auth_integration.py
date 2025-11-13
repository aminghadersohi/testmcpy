#!/usr/bin/env python3
"""
Test script to verify Phase 2.2 auth integration.

This script tests that:
1. TestCase can be created with auth config
2. TestResult has auth fields
3. Auth evaluators work with the test runner
"""

import asyncio
from testmcpy.src.test_runner import TestCase, TestResult, TestRunner
from testmcpy.evals.auth_evaluators import (
    AuthSuccessfulEvaluator,
    TokenValidEvaluator,
    OAuth2FlowEvaluator,
    AuthErrorHandlingEvaluator,
)


def test_testcase_with_auth():
    """Test that TestCase can be created with auth config."""
    print("\nTest 1: TestCase with auth config")

    test_data = {
        "name": "test_oauth",
        "prompt": "List datasets",
        "evaluators": [
            {"name": "auth_successful"},
            {"name": "token_valid", "args": {"format": "jwt"}},
        ],
        "auth": {
            "type": "oauth",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "token_url": "https://auth.example.com/token",
            "scopes": ["read", "write"],
        },
    }

    test_case = TestCase.from_dict(test_data)

    assert test_case.name == "test_oauth"
    assert test_case.auth is not None
    assert test_case.auth["type"] == "oauth"
    assert test_case.auth["client_id"] == "test-client"

    print("  ✓ TestCase can be created with auth config")


def test_testresult_with_auth():
    """Test that TestResult has auth fields."""
    print("\nTest 2: TestResult with auth fields")

    result = TestResult(
        test_name="test_oauth",
        passed=True,
        score=1.0,
        duration=1.5,
        reason="Auth successful",
        auth_success=True,
        auth_token="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
        auth_error=None,
        auth_error_message=None,
        auth_flow_steps=[
            "request_prepared",
            "token_endpoint_called",
            "response_received",
            "token_extracted",
        ],
    )

    assert result.auth_success is True
    assert result.auth_token is not None
    assert len(result.auth_flow_steps) == 4
    assert "token_extracted" in result.auth_flow_steps

    print("  ✓ TestResult has auth fields")


def test_auth_evaluators():
    """Test that auth evaluators work correctly."""
    print("\nTest 3: Auth evaluators")

    # Test AuthSuccessfulEvaluator
    print("  Testing AuthSuccessfulEvaluator...")
    evaluator = AuthSuccessfulEvaluator()

    context = {
        "metadata": {
            "auth_success": True,
            "auth_error": None,
            "auth_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
        }
    }

    result = evaluator.evaluate(context)
    assert result.passed is True
    assert result.score == 1.0
    print("    ✓ AuthSuccessfulEvaluator works")

    # Test TokenValidEvaluator
    print("  Testing TokenValidEvaluator...")
    evaluator = TokenValidEvaluator(args={"format": "jwt"})

    # Valid JWT token (header.payload.signature)
    jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

    context = {
        "metadata": {
            "auth_token": jwt_token,
        }
    }

    result = evaluator.evaluate(context)
    assert result.passed is True
    print("    ✓ TokenValidEvaluator works")

    # Test OAuth2FlowEvaluator
    print("  Testing OAuth2FlowEvaluator...")
    evaluator = OAuth2FlowEvaluator()

    context = {
        "metadata": {
            "auth_flow_steps": [
                "request_prepared",
                "token_endpoint_called",
                "response_received",
                "token_extracted",
            ]
        }
    }

    result = evaluator.evaluate(context)
    assert result.passed is True
    assert result.score == 1.0
    print("    ✓ OAuth2FlowEvaluator works")

    # Test AuthErrorHandlingEvaluator
    print("  Testing AuthErrorHandlingEvaluator...")
    evaluator = AuthErrorHandlingEvaluator(
        args={"required_info": ["invalid_client", "401"]}
    )

    context = {
        "metadata": {
            "auth_error": True,
            "auth_error_message": "Authentication failed: invalid_client (401 Unauthorized)",
        }
    }

    result = evaluator.evaluate(context)
    assert result.passed is True
    print("    ✓ AuthErrorHandlingEvaluator works")


def test_yaml_loading():
    """Test that auth_tests.yaml can be loaded."""
    print("\nTest 4: Loading auth_tests.yaml")

    import yaml

    with open("examples/auth_tests.yaml", "r") as f:
        data = yaml.safe_load(f)

    assert data["version"] == "1.0"
    assert data["name"] == "Authentication Test Suite"
    assert len(data["tests"]) > 0

    # Check first test has auth config
    first_test = data["tests"][0]
    assert "auth" in first_test
    assert first_test["auth"]["type"] == "oauth"

    print(f"  ✓ Loaded {len(data['tests'])} tests from auth_tests.yaml")

    # Verify we can create TestCase from YAML data
    test_case = TestCase.from_dict(first_test)
    assert test_case.auth is not None
    print("  ✓ Can create TestCase from YAML with auth")


def test_evaluator_factory():
    """Test that auth evaluators can be created via factory."""
    print("\nTest 5: Auth evaluator factory")

    from testmcpy.evals.base_evaluators import create_evaluator

    # Test creating each auth evaluator
    evaluators = [
        "auth_successful",
        "token_valid",
        "oauth2_flow_complete",
        "auth_error_handling",
    ]

    for name in evaluators:
        evaluator = create_evaluator(name)
        assert evaluator is not None
        print(f"  ✓ Created {name} evaluator")


def main():
    """Run all tests."""
    print("=" * 70)
    print("Testing Phase 2.2: Auth Integration")
    print("=" * 70)

    try:
        test_testcase_with_auth()
        test_testresult_with_auth()
        test_auth_evaluators()
        test_yaml_loading()
        test_evaluator_factory()

        print("\n" + "=" * 70)
        print("All tests passed!")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
