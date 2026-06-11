"""testmcpy evaluation functions."""

from testmcpy.evals.auth_evaluators import (
    AuthErrorHandlingEvaluator,
    AuthRejectsInvalidTokenEvaluator,
    AuthRejectsMissingTokenEvaluator,
    AuthSuccessfulEvaluator,
    AuthTokenNotEchoedEvaluator,
    JWTClaimsValidEvaluator,
    OAuth2FlowEvaluator,
    TokenValidEvaluator,
)
from testmcpy.evals.base_evaluators import (
    AnswerContainsLink,
    BaseEvaluator,
    CompositeEvaluator,
    EvalResult,
    ExecutionSuccessful,
    FinalAnswerContains,
    ParameterValueInRange,
    SQLQueryValid,
    TokenUsageReasonable,
    ToolCallCount,
    ToolCalledWithParameter,
    ToolCalledWithParameters,
    ToolCallSequence,
    WasChartCreated,
    WasMCPToolCalled,
    WithinTimeLimit,
    create_evaluator,
)
from testmcpy.evals.evaluator_packs import (
    list_packs,
    load_custom_packs_from_yaml,
    register_custom_pack,
    resolve_evaluator_pack,
    resolve_evaluators,
)
from testmcpy.evals.security_evaluators import NoInjectionEcho

# Backward compatibility alias
WasSupersetChartCreated = WasChartCreated

__all__ = [
    # Base evaluators
    "BaseEvaluator",
    "EvalResult",
    "WasMCPToolCalled",
    "ExecutionSuccessful",
    "FinalAnswerContains",
    "AnswerContainsLink",
    "WithinTimeLimit",
    "TokenUsageReasonable",
    "ToolCalledWithParameter",
    "ToolCalledWithParameters",
    "ParameterValueInRange",
    "ToolCallCount",
    "ToolCallSequence",
    "WasChartCreated",
    "WasSupersetChartCreated",  # Backward compatibility alias
    "SQLQueryValid",
    "CompositeEvaluator",
    "create_evaluator",
    # Security evaluators
    "NoInjectionEcho",
    # Auth evaluators
    "AuthSuccessfulEvaluator",
    "TokenValidEvaluator",
    "OAuth2FlowEvaluator",
    "AuthErrorHandlingEvaluator",
    "JWTClaimsValidEvaluator",
    "AuthRejectsMissingTokenEvaluator",
    "AuthRejectsInvalidTokenEvaluator",
    "AuthTokenNotEchoedEvaluator",
    # Evaluator packs
    "resolve_evaluator_pack",
    "resolve_evaluators",
    "list_packs",
    "register_custom_pack",
    "load_custom_packs_from_yaml",
]
