from pathlib import Path
import unittest


class FrontendContractTest(unittest.TestCase):
    def test_recommendation_strategy_selector_and_payload_are_present(self):
        source = Path(__file__).resolve().parents[2] / "frontend" / "src"
        app_content = (source / "App.jsx").read_text(encoding="utf-8")
        form_content = (source / "features" / "recommendations" / "RecommendationForm.jsx").read_text(encoding="utf-8")
        results_content = (source / "features" / "recommendations" / "RecommendationResults.jsx").read_text(encoding="utf-8")
        api_content = (source / "api" / "sigraApi.js").read_text(encoding="utf-8")

        self.assertIn("recommendation_strategy", app_content)
        self.assertIn("Prioridade da recomendação", form_content)
        self.assertIn("JSON.stringify(profile)", api_content)
        self.assertIn("Limite mensal", form_content)
        self.assertIn("metadata?.has_viable_options === false", results_content)
        self.assertIn("Nenhuma opção atende integralmente", results_content)


if __name__ == "__main__":
    unittest.main()
