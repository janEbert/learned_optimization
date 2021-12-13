# coding=utf-8
# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Utilities for testing tasks and task families."""

from absl import logging
import jax
from learned_optimization.tasks import base


def smoketest_task(task: base.Task):
  """Smoke test a Task."""
  key = jax.random.PRNGKey(0)
  param, state = task.init(key)

  logging.info("Getting data for %s task", str(task))
  if task.datasets:
    batch = next(task.datasets.train)
  else:
    batch = ()
  logging.info("Got data")

  logging.info("starting forward")
  loss = task.loss(param, state, key, batch)
  del loss
  logging.info("starting backward")
  grad, aux = jax.grad(task.loss, has_aux=True)(param, state, key, batch)
  del grad, aux
  logging.info("done")


def smoketest_task_family(task_family: base.TaskFamily):
  """Smoke test a TaskFamily."""
  key = jax.random.PRNGKey(0)
  task_params = task_family.sample(key)
  task = task_family.task_fn(task_params)
  smoketest_task(task)

  _, key = jax.random.split(key)
  task_params = task_family.sample(key)
  task = task_family.task_fn(task_params)
  smoketest_task(task)

  if task.datasets is not None:
    assert task_family.datasets is not None