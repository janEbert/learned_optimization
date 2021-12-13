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

"""Base class for Optimizer and a couple hand designed optimizer."""
import abc
import collections
import functools
from typing import Any, Tuple, Optional, Sequence, Callable
import gin
import jax
import jax.numpy as jnp
import optax

# pytree containing jax types
ModelState = Any
Params = Any
Gradient = Params
OptState = Any
PRNGKey = jnp.ndarray  # pylint: disable=invalid-name

StatelessState = collections.namedtuple("StatelessState", ["params", "state"])


class Optimizer(abc.ABC):
  """Baseclass for the Optimizer interface."""

  def get_params(self, state: OptState) -> Params:
    return state.params

  def get_state(self, state: OptState) -> ModelState:
    return state.state

  def get_params_state(self, state: OptState) -> Tuple[Params, ModelState]:
    return self.get_params(state), self.get_state(state)

  def init(self,
           params: Params,
           state: ModelState = None,
           num_steps: Optional[int] = None,
           key: Optional[PRNGKey] = None) -> OptState:
    raise NotImplementedError

  def set_params(self, state: OptState, params: Params) -> OptState:
    return state._replace(params=params)

  def update(
      self,
      opt_state: OptState,
      grad: Gradient,
      loss: jnp.asarray = None,
      model_state: ModelState = None,
      is_valid: jnp.asarray = False,
      key: PRNGKey = None,
  ) -> OptState:
    raise NotImplementedError


# Internal-ish states
OptaxState = collections.namedtuple(
    "OptaxState", ["params", "state", "optax_opt_state", "iteration"])


class OptaxOptimizer(Optimizer):
  """Wrapper to convert optax optimizers into `Optimizers`."""

  def __init__(self, opt: optax.GradientTransformation):
    super().__init__()
    self.opt = opt

  def init(self,
           params: Params,
           state: ModelState = None,
           num_steps: Optional[int] = None,
           key: Optional[PRNGKey] = None):
    return OptaxState(
        params=params,
        optax_opt_state=self.opt.init(params),
        state=state,
        iteration=0)

  @functools.partial(jax.jit, static_argnums=(0,))
  def update(self,
             opt_state: OptaxState,
             grad: Gradient,
             loss: Optional[jnp.ndarray],
             model_state: Optional[ModelState] = None,
             is_valid: bool = False,
             key: Optional[PRNGKey] = None):
    update, new_opt_state = self.opt.update(grad, opt_state.optax_opt_state,
                                            opt_state.params)
    return OptaxState(
        state=model_state,
        params=optax.apply_updates(opt_state.params, update),
        optax_opt_state=new_opt_state,
        iteration=opt_state.iteration + 1,
    )


@gin.configurable
class SGD(OptaxOptimizer):
  """Stochastic gradient descent."""

  def __init__(self, learning_rate=0.01):
    opt = optax.sgd(learning_rate)
    super().__init__(opt)


@gin.configurable
class SGDM(OptaxOptimizer):
  """Stochastic gradient descent with momentum."""

  def __init__(self, learning_rate=0.01, momentum=0.9):
    opt = optax.sgd(learning_rate, momentum)
    super().__init__(opt)


@gin.configurable
class Adam(OptaxOptimizer):
  """Adam optimizer."""

  def __init__(self,
               learning_rate=0.01,
               beta1=0.9,
               beta2=0.999,
               epsilon=1e-8,
               epsilon_root=1e-8):
    opt = optax.adam(
        learning_rate=learning_rate,
        b1=beta1,
        b2=beta2,
        eps=epsilon,
        eps_root=epsilon_root)
    super().__init__(opt)


def piecewise_linear(times: Sequence[float],
                     vals: Sequence[float]) -> Callable[[float], float]:
  """Returns a function which interpolates piecewise values."""
  times = jnp.asarray(times)
  vals = jnp.asarray(vals)

  def fn(x):
    if len(times) <= 1:
      assert len(vals) == 1
      return vals[0]

    vs = []

    all_before = jnp.all(x <= times)
    all_after = jnp.all(x >= times)

    for i in range(len(times) - 1):
      x1 = times[i]
      x2 = times[i + 1]
      y1 = vals[i]
      y2 = vals[i + 1]
      m = (y2 - y1) / (x2 - x1)
      v = (x - x1) * m + y1
      vs.append(v)
    idx = jnp.sum(x > times) - 1

    mid = jnp.take(jnp.asarray(vs), idx)
    return all_before * vals[0] + all_after * vals[-1] + mid * (
        (1 - all_before) * (1 - all_after))

  return fn


@gin.configurable
class PiecewiseLinearAdam(OptaxOptimizer):
  """Adam with a piecewise linear learning rate schedule."""

  def __init__(self,
               times=(10000, 20000),
               lrs=(1e-4, 1e-5),
               beta1=0.9,
               beta2=0.999,
               epsilon=1e-8,
               epsilon_root=1e-8):
    opt = optax.chain(
        optax.scale_by_adam(
            b1=beta1, b2=beta2, eps=epsilon, eps_root=epsilon_root),
        optax.scale_by_schedule(piecewise_linear(times, vals=lrs)),
        optax.scale(-1),
    )
    super().__init__(opt)


@gin.configurable
class RMSProp(OptaxOptimizer):
  """RMSProp optimizer (including momentum)."""

  def __init__(
      self,
      learning_rate=0.01,
      decay=0.9,
      epsilon=1e-8,
      momentum=0.0,
      nesterov=False,
  ):
    opt = optax.rmsprop(
        learning_rate=learning_rate,
        decay=decay,
        eps=epsilon,
        nesterov=nesterov,
        momentum=momentum,
    )
    super().__init__(opt)