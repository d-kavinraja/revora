from typing import Dict, Any, List
from app.verification.validators import ValidationResult

class ConfidenceEngine:
    """Calculates confidence scores based on validation results."""
    
    BASE_SCORE = 0.5  # Start at 50%
    THRESHOLD_REJECT = 0.40
    THRESHOLD_NEEDS_REVIEW = 0.70
    THRESHOLD_GOOD = 0.90
    
    def calculate(self, finding: Dict[str, Any], validation_results: List[ValidationResult]) -> float:
        """
        Returns a confidence score between 0.0 and 1.0.
        """
        score = self.BASE_SCORE
        
        for result in validation_results:
            score += result.score_modifier
            
        # Ensure score is bound between 0 and 1
        score = max(0.0, min(1.0, score))
        
        return score
        
    def get_status(self, score: float) -> str:
        if score <= self.THRESHOLD_REJECT:
            return "REJECT"
        elif score <= self.THRESHOLD_NEEDS_REVIEW:
            return "NEEDS_REVIEW"
        elif score <= self.THRESHOLD_GOOD:
            return "GOOD"
        else:
            return "HIGH_CONFIDENCE"
