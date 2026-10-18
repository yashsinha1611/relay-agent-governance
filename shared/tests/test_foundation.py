import os
import socket
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from shared.llm.provider import ModelConfig, ProviderConfigurationError, get_model
from shared.schemas import Action, Plan


class FoundationTests(unittest.TestCase):
    def test_offline_determinism_and_parsing(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ):
            model = get_model()
            self.assertEqual(model.invoke('{"subtasks":[]}'), model.invoke('{"subtasks":[]}'))
            self.assertEqual(model.invoke_structured('{"subtasks":[]}', Plan), Plan())
            import relay
            import tribunal
            self.assertIsNotNone(relay)
            self.assertIsNotNone(tribunal)

    def test_explicit_mock(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}):
            self.assertEqual(get_model().mode, "mock")

    def test_invalid_schema(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}):
            with self.assertRaises(ValidationError):
                get_model().invoke_structured('{"unexpected": true}', Plan)
        with self.assertRaises(ValidationError):
            Action(operation="shell", target="anything")

    def test_configuration_without_network(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}, clear=True):
                with self.assertRaises(ProviderConfigurationError):
                    get_model()
                with self.assertRaises(ProviderConfigurationError):
                    get_model(ModelConfig(model="explicit"))
            with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}):
                with self.assertRaises(ProviderConfigurationError):
                    get_model()
            with patch.dict(os.environ, {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-only"}):
                self.assertEqual(get_model(ModelConfig(model="explicit")).mode, "openai")

    def test_dependency_cycles(self):
        action = {"operation": "upload", "target": "relay-dev-raw"}
        with self.assertRaises(ValidationError):
            Plan.model_validate({"subtasks": [
                {"id": "a", "specialist": "storage", "action": action, "depends_on": ["b"]},
                {"id": "b", "specialist": "storage", "action": action, "depends_on": ["a"]},
            ]})


if __name__ == "__main__":
    unittest.main()