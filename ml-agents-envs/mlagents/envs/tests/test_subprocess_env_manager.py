import unittest.mock as mock
from unittest.mock import Mock, MagicMock
import unittest
import cloudpickle

from mlagents.envs.subprocess_env_manager import (
    SubprocessEnvManager,
    EnvironmentResponse,
    EnvironmentCommand,
    worker,
)
from mlagents.envs.base_unity_environment import BaseUnityEnvironment


def mock_env_factory(worker_id: int):
    return mock.create_autospec(spec=BaseUnityEnvironment)


class MockEnvWorker:
    def __init__(self, worker_id, resp=None):
        self.worker_id = worker_id
        self.process = None
        self.conn = None
        self.send = Mock()
        self.recv = Mock(return_value=resp)


class SubprocessEnvManagerTest(unittest.TestCase):
    def test_environments_are_created(self):
        SubprocessEnvManager.create_worker = MagicMock()
        env = SubprocessEnvManager(mock_env_factory, 2)
        # Creates two processes
        env.create_worker.assert_has_calls(
            [mock.call(0, mock_env_factory), mock.call(1, mock_env_factory)]
        )
        self.assertEqual(len(env.env_workers), 2)

    def test_worker_step_resets_on_global_done(self):
        env_mock = Mock()
        env_mock.reset = Mock(return_value="reset_data")
        env_mock.global_done = True

        def mock_global_done_env_factory(worker_id: int):
            return env_mock

        mock_parent_connection = Mock()
        step_command = EnvironmentCommand("step", (None, None, None, None))
        close_command = EnvironmentCommand("close")
        mock_parent_connection.recv.side_effect = [step_command, close_command]
        mock_parent_connection.send = Mock()

        worker(
            mock_parent_connection, cloudpickle.dumps(mock_global_done_env_factory), 0
        )

        # recv called twice to get step and close command
        self.assertEqual(mock_parent_connection.recv.call_count, 2)

        # worker returns the data from the reset
        mock_parent_connection.send.assert_called_with(
            EnvironmentResponse("step", 0, "reset_data")
        )

    def test_reset_passes_reset_params(self):
        manager = SubprocessEnvManager(mock_env_factory, 1)
        params = {"test": "params"}
        manager.reset(params, False)
        manager.env_workers[0].send.assert_called_with("reset", (params, False, None))

    def test_reset_collects_results_from_all_envs(self):
        SubprocessEnvManager.create_worker = lambda em, worker_id, env_factory: MockEnvWorker(
            worker_id, EnvironmentResponse("reset", worker_id, worker_id)
        )
        manager = SubprocessEnvManager(mock_env_factory, 4)

        params = {"test": "params"}
        res = manager.reset(params)
        for i, env in enumerate(manager.env_workers):
            env.send.assert_called_with("reset", (params, True, None))
            env.recv.assert_called()
            # Check that the "last steps" are set to the value returned for each step
            self.assertEqual(
                manager.env_workers[i].previous_step.current_all_brain_info, i
            )
        assert res == list(map(lambda ew: ew.previous_step, manager.env_workers))

    def test_step_takes_steps_for_all_envs(self):
        SubprocessEnvManager.create_worker = lambda em, worker_id, env_factory: MockEnvWorker(
            worker_id, EnvironmentResponse("step", worker_id, worker_id)
        )
        manager = SubprocessEnvManager(mock_env_factory, 2)
        step_mock = Mock()
        last_steps = [Mock(), Mock()]
        manager.env_workers[0].previous_step = last_steps[0]
        manager.env_workers[1].previous_step = last_steps[1]
        manager._take_step = Mock(return_value=step_mock)
        res = manager.step()
        for i, env in enumerate(manager.env_workers):
            env.send.assert_called_with("step", step_mock)
            env.recv.assert_called()
            # Check that the "last steps" are set to the value returned for each step
            self.assertEqual(
                manager.env_workers[i].previous_step.current_all_brain_info, i
            )
            self.assertEqual(
                manager.env_workers[i].previous_step.previous_all_brain_info,
                last_steps[i].current_all_brain_info,
            )
        assert res == list(map(lambda ew: ew.previous_step, manager.env_workers))
