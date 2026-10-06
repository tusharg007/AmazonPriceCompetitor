from app.core.exceptions import ApplicationError


class AnalysisError(ApplicationError):
    def __init__(
        self, message: str = "Analysis output could not be validated. Please retry."
    ) -> None:
        super().__init__(message, "analysis_failed", 409)
