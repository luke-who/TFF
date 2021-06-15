# -*- coding: utf-8 -*-
"""Copy of custom_aggregators.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/10kN7CyYJzxVIz36jNSbigmQ99JERqt2B

##### Copyright 2021 The TensorFlow Federated Authors.
"""

#@title Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""# Implementing Custom Aggregations

<table class="tfo-notebook-buttons" align="left">
  <td>
    <a target="_blank" href="https://www.tensorflow.org/federated/tutorials/custom_aggregators"><img src="https://www.tensorflow.org/images/tf_logo_32px.png" />View on TensorFlow.org</a>
  </td>
  <td>
    <a target="_blank" href="https://colab.research.google.com/github/tensorflow/federated/blob/master/docs/tutorials/custom_aggregators.ipynb"><img src="https://www.tensorflow.org/images/colab_logo_32px.png" />Run in Google Colab</a>
  </td>
  <td>
    <a target="_blank" href="https://github.com/tensorflow/federated/blob/master/docs/tutorials/custom_aggregators.ipynb"><img src="https://www.tensorflow.org/images/GitHub-Mark-32px.png" />View source on GitHub</a>
  </td>
  <td>
    <a href="https://storage.googleapis.com/tensorflow_docs/federated/docs/tutorials/custom_aggregators.ipynb"><img src="https://www.tensorflow.org/images/download_logo_32px.png" />Download notebook</a>
  </td>
</table>

In this tutorial, we explain design principles behind the `tff.aggregators` module and best practices for implementing custom aggregation of values from clients to server.

**Prerequisites.** This tutorial assumes you are already familiar with basic concepts of [Federated Core](https://www.tensorflow.org/federated/federated_core) such as placements (`tff.SERVER`, `tff.CLIENTS`), how TFF represents computations (`tff.tf_computation`, `tff.federated_computation`) and their type signatures.
"""

#@test {"skip": true}
!pip install --quiet --upgrade tensorflow_federated_nightly
!pip install --quiet --upgrade nest_asyncio

import nest_asyncio
nest_asyncio.apply()

"""## Design summary

In TFF, "aggregation" refers to the movement of a set of values on `tff.CLIENTS` to produce an aggregate value of the same type on `tff.SERVER`. That is, each individual client value need not be available. For example in federated learning, client model updates are averaged to get an aggregate model update to apply to the global model on the server.

In addition to operators accomplishing this goal such as `tff.federated_sum`, TFF provides `tff.templates.AggregationProcess` (a [stateful process](https://www.tensorflow.org/federated/federated_learning#modeling_state)) which formalizes the type signature for aggregation computation so it can generalize to more complex forms than a simple sum.

The main components of the `tff.aggregators` module are *factories* for creation of the `AggregationProcess`, which are designed to be generally useful and replacable building blocks of TFF in two aspects:

1. *Parameterized computations.* Aggregation is an independent building block that can be plugged into other TFF modules designed to work with `tff.aggregators` to parameterize their necessary aggregation.

Example:

```
learning_process = tff.learning.build_federated_averaging_process(
    ...,
    model_update_aggregation_factory=tff.aggregators.MeanFactory())
```

2. *Aggregation composition.* An aggregation building block can be composed with other aggregation building blocks to create more complex composite aggregations.

Example:

```
secure_mean = tff.aggregators.MeanFactory(
    value_sum_factory=tff.aggregators.SecureSumFactory(...))
```

The rest of this tutorial explains how these two goals are achieved.

### Aggregation process

We first summarize the `tff.templates.AggregationProcess`, and follow with the factory pattern for its creation.

The `tff.templates.AggregationProcess` is an `tff.templates.MeasuredProcess` with type signatures specified for aggregation. In particular, the `initialize` and `next` functions have the following type signatures:

* `( -> state_type@SERVER)`
* `(<state_type@SERVER, {value_type}@CLIENTS, *> -> <state_type@SERVER, value_type@SERVER, measurements_type@SERVER>)`

The state (of type `state_type`) must be placed at server. The `next` function takes as input argument the state and a value to be aggregated (of type `value_type`) placed at clients. The `*` means optional other input arguments, for instance weights in a weighted mean. It returns an updated state object, the aggregated value of the same type placed at server, and some measurements.

Note that both the state to be passed between executions of the `next` function, and the reported measurements intended to report any information depending on a specific execution of the `next` function, may be empty. Nevertheless, they have to be explicitly specified for other parts of TFF to have a clear contract to follow.

Other TFF modules, for instance the model updates in `tff.learning`, are expected to use the `tff.templates.AggregationProcess` to parameterize how values are aggregated. However, what exactly are the values aggregated and what their type signatures are, depends on other details of the model being trained and the learning algorithm used to do it.

To make aggregation independent of the other aspects of computations, we use the factory pattern -- we create the appropriate `tff.templates.AggregationProcess` once the relevant type signatures of objects to be aggregated are available, by invoking the `create` method of the factory. Direct handling of the aggregation process is thus needed only for library authors, who are responsible for this creation.

#### Aggregation process factories

There are two abstract base factory classes for unweighted and weighted aggregation. Their `create` method takes type signatures of value to be aggregated and returns a `tff.templates.AggregationProcess` for aggregation of such values.

The process created by `tff.aggregators.UnweightedAggregationFactory` takes two input arguments: (1) state at server and (2) value of specified type `value_type`.

An example implementation is `tff.aggregators.SumFactory`.

The process created by `tff.aggregators.WeightedAggregationFactory` takes three input arguments: (1) state at server, (2) value of specified type `value_type` and (3) weight of type `weight_type`, as specified by the factory's user when invoking its `create` method.

An example implementation is `tff.aggregators.MeanFactory` which computes a weighted mean.

The factory pattern is how we achieve the first goal stated above; that aggregation is an independent building block. For example, when changing which model variables are trainable, a complex aggregation does not necessarily need to change; the factory representing it will be invoked with a different type signature when used by a method such as `tff.learning.build_federated_averaging_process`.

### Compositions

Recall that a general aggregation process can encapsulate (a) some preprocessing of the values at clients, (b) movement of values from client to server, and (c) some postprocessing of the aggregated value at the server. The second goal stated above, aggregation composition, is realized inside the `tff.aggregators` module by structuring the implementation of the aggregation factories such that part (b) can be delegated to another aggregation factory.

Rather than implementing all necessary logic within a single factory class, the implementations are by default focused on a single aspect relevant for aggregation. When needed, this pattern then enables us to replace the building blocks one at a time.

An example is the weighted `tff.aggregators.MeanFactory`. Its implementation multiplies provided values and weights at clients, then sums both weighted values and weights independently, and then divides the sum of weighted values by the sum of weights at the server. Instead of implementing the summations by directly using the `tff.federated_sum` operator, the summation is delegated to two instances of `tff.aggregators.SumFactory`.

Such structure makes it possible for the two default summations to be replaced by different factories, which realize the sum differently. For example, a `tff.aggregators.SecureSumFactory`, or a custom implementation of the `tff.aggregators.UnweightedAggregationFactory`. Conversely, time, `tff.aggregators.MeanFactory` can itself be an inner aggregation of another factory such as `tff.aggregators.clipping_factory`, if the values are to be clipped before averaging.

See the previous [Tuning recommended aggregations for learning](tuning_recommended_aggregators.ipynb) tutorial for receommended uses of the composition mechanism using existing factories in the `tff.aggregators` module.

## Best practices by example

We are going to illustrate the `tff.aggregators` concepts in detail by implementing a simple example task, and make it progressively more general. Another way to learn is to look at the implementation of existing factories.
"""

import collections
import tensorflow as tf
import tensorflow_federated as tff

import attr
import functools
import numpy as np

import tensorflow_probability as tfp

"""Instead of summing `value`, the example task is to sum `value * 2.0` and then divide the sum by `2.0`. The aggregation result is thus mathematically equivalent to directly summing the `value`, and could be thought of as consisting of three parts: (1) scaling at clients (2) summing across clients (3) unscaling at server.

NOTE: This task is not necessarily useful in practice. Nevertheless, it is helpful in explaining the underlying concepts.

Following the design explained above, the logic will be implemented as a subclass of `tff.aggregators.UnweightedAggregationFactory`, which creates appropriate `tff.templates.AggregationProcess` when given a `value_type` to aggregate:

### Minimal implementation

For the example task, the computations necessary are always the same, so there is no need for using state. It is thus empty, and represented as `tff.federated_value((), tff.SERVER)`. The same holds for measurements, for now.

The minimal implementation of the task is thus as follows:
"""

class ExampleTaskFactory(tff.aggregators.UnweightedAggregationFactory):

  def create(self, value_type):
    @tff.federated_computation()
    def initialize_fn():
      return tff.federated_value((), tff.SERVER)

    @tff.federated_computation(initialize_fn.type_signature.result,
                               tff.type_at_clients(value_type))
    def next_fn(state, value):
      scaled_value = tff.federated_map(
          tff.tf_computation(lambda x: x * 2.0), value)
      summed_value = tff.federated_sum(scaled_value)
      unscaled_value = tff.federated_map(
          tff.tf_computation(lambda x: x / 2.0), summed_value)
      measurements = tff.federated_value((), tff.SERVER)
      return tff.templates.MeasuredProcessOutput(
          state=state, result=unscaled_value, measurements=measurements)

    return tff.templates.AggregationProcess(initialize_fn, next_fn)

"""Whether everything works as expected can be verified with the following code:"""

client_data = (1.0, 2.0, 5.0)
factory = ExampleTaskFactory()
aggregation_process = factory.create(tff.TensorType(tf.float32))
print(f'Type signatures of the created aggregation process:\n'
      f'  - initialize: {aggregation_process.initialize.type_signature}\n'
      f'  - next: {aggregation_process.next.type_signature}\n')

state = aggregation_process.initialize()
output = aggregation_process.next(state, client_data)
print(f'Aggregation result: {output.result}  (expected 8.0)')

"""### Statefulness and measurements

Statefulness is broadly used in TFF to represent computations that are expected to be executed iteratively and change with each iteration. For example, the state of a learning computation contains the weights of the model being learned.

To illustrate how to use state in an aggregation computation, we modify the example task. Instead of multiplying `value` by `2.0`, we multiply it by the iteration index - the number of times the aggregation has been executed.

To do so, we need a way to keep track of the iteration index, which is achieved through the concept of state. In the `initialize_fn`, instead of creating an empty state, we initialize the state to be a scalar zero. Then, state can be used in the `next_fn` in three steps: (1) increment by `1.0`, (2) use to multiply `value`, and (3) return as the new updated state.

Once this is done, you may note: *But exactly the same code as above can be used to verify all works as expected. How do I know something has actually changed?*

Good question! This is where the concept of measurements becomes useful. In general, measurements can report any value relevant to a single execution of the `next` function, which could be used for monitoring. In this case, it can be the `summed_value` from the previous example. That is, the value before the "unscaling" step, which should depend on the iteration index. *Again, this is not necessarily useful in practice, but illustrates the relevant mechanism.*

The stateful answer to the task thus looks as follows:
"""

# @tff.tf_computation()
# def median(value):
#   n = value.shape[0]
#   value = tf.sort(value)
#   if n % 2 == 0:
#     median1 = value[n//2]
#     median2 = value[n//2 - 1]
#     median = tf.divide(tf.add(median1,median2),2)
#   else:
#     median = value[n//2]
#   return median
# # print(median(client_data))

# def median(value):
#   with tf.compat.v1.Session() as ses:
#     # Calculate median.
#     value=value.numpy().tolist()
#     median_ = tfp.stats.percentile(value, 50.0, interpolation='midpoint')
#     # Evaluate the tensor `median`.
#     median = ses.run(median_)
#   return median

def median(value):
  median = np.float32(np.percentile(value, 50, interpolation='midpoint'))
  return median

class ExampleTaskFactory(tff.aggregators.UnweightedAggregationFactory):

  def create(self, value_type):
    @tff.federated_computation()
    def initialize_fn():
      return tff.federated_value(0.0, tff.SERVER)

    @tff.federated_computation(initialize_fn.type_signature.result,
                               tff.type_at_clients(value_type))
    def next_fn(state, value):
      new_state = tff.federated_map(
          tff.tf_computation(lambda x: x + 1.0), state)
      state_at_clients = tff.federated_broadcast(new_state)
      scaled_value = tff.federated_map(
          tff.tf_computation(lambda x, y: x * y), (value, state_at_clients))
      summed_value = tff.federated_sum(scaled_value)
      unscaled_value = tff.federated_map(
          tff.tf_computation(lambda x, y: x / y), (summed_value, new_state))
      ####******calculate median*****####
      # median_value = tff.federated_map(
      #     tff.tf_computation(lambda x: median(x)), value)
      # median_value_at_server = tff.federated_sum(median_value)
      return tff.templates.MeasuredProcessOutput(
          state=new_state, result=unscaled_value, measurements=summed_value)

    return tff.templates.AggregationProcess(initialize_fn, next_fn)

"""Note that the `state` that comes into `next_fn` as input is placed at server. In order to use it at clients, it first needs to be communicated, which is achieved using the `tff.federated_broadcast` operator.

To verify all works as expected, we can now look at the reported `measurements`, which should be different with each round of execution, even if run with the same `client_data`.
"""

client_data = (1.0, 2.0, 5.0)
factory = ExampleTaskFactory()
aggregation_process = factory.create(tff.TensorType(tf.float32))
print(f'Type signatures of the created aggregation process:\n'
      f'  - initialize: {aggregation_process.initialize.type_signature}\n'
      f'  - next: {aggregation_process.next.type_signature}\n')

state = aggregation_process.initialize()

output = aggregation_process.next(state, client_data)
print('| Round #1')
print(f'|       Aggregation result: {output.result}   (expected 8.0)')
print(f'| Aggregation measurements: {output.measurements}   (expected 8.0 * 1)')

output = aggregation_process.next(output.state, client_data)
print('\n| Round #2')
print(f'|       Aggregation result: {output.result}   (expected 8.0)')
print(f'| Aggregation measurements: {output.measurements}  (expected 8.0 * 2)')

output = aggregation_process.next(output.state, client_data)
print('\n| Round #3')
print(f'|       Aggregation result: {output.result}   (expected 8.0)')
print(f'| Aggregation measurements: {output.measurements}  (expected 8.0 * 3)')

"""### Structured types

The model weights of a model trained in federated learning are usually represented as a collection of tensors, rather than a single tensor. In TFF, this is represented as `tff.StructType` and generally useful aggregation factories need to be able to accept the structured types.

However, in the above examples, we only worked with a `tff.TensorType` object. If we try to use the previous factory to create the aggregation process with a `tff.StructType([(tf.float32, (2,)), (tf.float32, (3,))])`, we get a strange error because TensorFlow will try to multiply a `tf.Tensor` and a `list`.

The problem is that instead of multiplying the structure of tensors by a constant, we need to multiply *each tensor in the structure* by a constant. The usual solution to this problem is to use the `tf.nest` module inside of the created `tff.tf_computation`s.

The version of the previous `ExampleTaskFactory` compatible with structured types thus looks as follows:
"""

@tff.tf_computation()
def scale(value, factor):
  return tf.nest.map_structure(lambda x: x * factor, value)

@tff.tf_computation()
def unscale(value, factor):
  return tf.nest.map_structure(lambda x: x / factor, value)

@tff.tf_computation()
def add_one(value):
  return value + 1.0

class ExampleTaskFactory(tff.aggregators.UnweightedAggregationFactory):

  def create(self, value_type):
    @tff.federated_computation()
    def initialize_fn():
      return tff.federated_value(0.0, tff.SERVER)

    @tff.federated_computation(initialize_fn.type_signature.result,
                               tff.type_at_clients(value_type))
    def next_fn(state, value):
      new_state = tff.federated_map(add_one, state)
      state_at_clients = tff.federated_broadcast(new_state)
      scaled_value = tff.federated_map(scale, (value, state_at_clients))
      summed_value = tff.federated_sum(scaled_value)
      unscaled_value = tff.federated_map(unscale, (summed_value, new_state))
      return tff.templates.MeasuredProcessOutput(
          state=new_state, result=unscaled_value, measurements=summed_value)

    return tff.templates.AggregationProcess(initialize_fn, next_fn)

"""This example highlights a pattern which may be useful to follow when structuring TFF code. When not dealing with very simple operations, the code becomes more legible when the `tff.tf_computation`s that will be used as building blocks inside a `tff.federated_computation` are created in a separate place. Inside of the `tff.federated_computation`, these building blocks are only connected using the intrinsic operators.

To verify it works as expected:
"""

client_data = [[[1.0, 2.0], [3.0, 4.0, 5.0]],
               [[1.0, 1.0], [3.0, 0.0, -5.0]]]
factory = ExampleTaskFactory()
aggregation_process = factory.create(
    tff.to_type([(tf.float32, (2,)), (tf.float32, (3,))]))
print(f'Type signatures of the created aggregation process:\n'
      f'  - initialize: {aggregation_process.initialize.type_signature}\n'
      f'  - next: {aggregation_process.next.type_signature}\n')

state = aggregation_process.initialize()
output = aggregation_process.next(state, client_data)
print(f'Aggregation result: [{output.result[0]}, {output.result[1]}]\n'
      f'          Expected: [[2. 3.], [6. 4. 0.]]')

"""### Inner aggregations

The final step is to optionally enable delegation of the actual aggregation to other factories, in order to allow easy composition of different aggregation techniques.

This is achieved by creating an optional `inner_factory` argument in the constructor of our `ExampleTaskFactory`. If not specified, `tff.aggregators.SumFactory` is used, which applies the `tff.federated_sum` operator used directly in the previous section.

When `create` is called, we can first call `create` of the `inner_factory` to create the inner aggregation process with the same `value_type`.

The state of our process returned by `initialize_fn` is a composition of two parts: the state created by "this" process, and the state of the just created inner process.

The implementation of the `next_fn` differs in that the actual aggregation is delegated to the `next` function of the inner process, and in how the final output is composed. The state is again composed of "this" and "inner" state, and measurements are composed in a similar manner as an `OrderedDict`.

The following is an implementation of such pattern.
"""

@tff.tf_computation()
def scale(value, factor):
  return tf.nest.map_structure(lambda x: x * factor, value)

@tff.tf_computation()
def unscale(value, factor):
  return tf.nest.map_structure(lambda x: x / factor, value)

@tff.tf_computation()
def add_one(value):
  return value + 1.0

class ExampleTaskFactory(tff.aggregators.UnweightedAggregationFactory):

  def __init__(self, inner_factory=None):
    if inner_factory is None:
      inner_factory = tff.aggregators.SumFactory()
    self._inner_factory = inner_factory

  def create(self, value_type):
    inner_process = self._inner_factory.create(value_type)

    @tff.federated_computation()
    def initialize_fn():
      my_state = tff.federated_value(0.0, tff.SERVER)
      inner_state = inner_process.initialize()
      return tff.federated_zip((my_state, inner_state))

    @tff.federated_computation(initialize_fn.type_signature.result,
                               tff.type_at_clients(value_type))
    def next_fn(state, value):
      my_state, inner_state = state
      my_new_state = tff.federated_map(add_one, my_state)
      my_state_at_clients = tff.federated_broadcast(my_new_state)
      scaled_value = tff.federated_map(scale, (value, my_state_at_clients))

      # Delegation to an inner factory, returning values placed at SERVER.
      inner_output = inner_process.next(inner_state, scaled_value)

      unscaled_value = tff.federated_map(unscale, (inner_output.result, my_new_state))

      new_state = tff.federated_zip((my_new_state, inner_output.state))
      measurements = tff.federated_zip(
          collections.OrderedDict(
              scaled_value=inner_output.result,
              example_task=inner_output.measurements))

      return tff.templates.MeasuredProcessOutput(
          state=new_state, result=unscaled_value, measurements=measurements)

    return tff.templates.AggregationProcess(initialize_fn, next_fn)

"""When delegating to the `inner_process.next` function, the return structure we get is a `tff.templates.MeasuredProcessOutput`, with the same three fields - `state`, `result` and `measurements`. When creating the overall return structure of the composed aggregation process, the `state` and `measurements` fields should be generally composed and returned together. In contrast, the `result` field corresponds to the value being aggregated and instead "flows through" the composed aggregation.

The `state` object should be seen as an implementation detail of the factory, and thus the composition could be of any structure. However, `measurements` correspond to values to be reported to the user at some point. Therefore, we recommend to use `OrderedDict`, with composed naming such that it would be clear where in an composition does a reported metric comes from.

Note also the use of the `tff.federated_zip` operator. The `state` object contolled by the created process should be a `tff.FederatedType`. If we had instead returned `(this_state, inner_state)` in the `initialize_fn`, its return type signature would be a `tff.StructType` containing a 2-tuple of `tff.FederatedType`s. The use of `tff.federated_zip` "lifts" the `tff.FederatedType` to the top level. This is similarly used in the `next_fn` when preparing the state and measurements to be returned.

Finally, we can see how this can be used with the default inner aggregation:
"""

client_data = (1.0, 2.0, 5.0)
factory = ExampleTaskFactory()
aggregation_process = factory.create(tff.TensorType(tf.float32))
state = aggregation_process.initialize()

output = aggregation_process.next(state, client_data)
print('| Round #1')
print(f'|           Aggregation result: {output.result}   (expected 8.0)')
print(f'| measurements[\'scaled_value\']: {output.measurements["scaled_value"]}')
print(f'| measurements[\'example_task\']: {output.measurements["example_task"]}')

output = aggregation_process.next(output.state, client_data)
print('\n| Round #2')
print(f'|           Aggregation result: {output.result}   (expected 8.0)')
print(f'| measurements[\'scaled_value\']: {output.measurements["scaled_value"]}')
print(f'| measurements[\'example_task\']: {output.measurements["example_task"]}')

"""... and with a different inner aggregation. For example, an `ExampleTaskFactory`:"""

client_data = (1.0, 2.0, 5.0)
# Note the inner delegation can be to any UnweightedAggregaionFactory.
# In this case, each factory creates process that multiplies by the iteration
# index (1, 2, 3, ...), thus their combination multiplies by (1, 4, 9, ...).
factory = ExampleTaskFactory(ExampleTaskFactory())
aggregation_process = factory.create(tff.TensorType(tf.float32))
state = aggregation_process.initialize()

output = aggregation_process.next(state, client_data)
print('| Round #1')
print(f'|           Aggregation result: {output.result}   (expected 8.0)')
print(f'| measurements[\'scaled_value\']: {output.measurements["scaled_value"]}')
print(f'| measurements[\'example_task\']: {output.measurements["example_task"]}')

output = aggregation_process.next(output.state, client_data)
print('\n| Round #2')
print(f'|           Aggregation result: {output.result}   (expected 8.0)')
print(f'| measurements[\'scaled_value\']: {output.measurements["scaled_value"]}')
print(f'| measurements[\'example_task\']: {output.measurements["example_task"]}')

"""## Summary

In this tutorial, we explained the best practices to follow in order to create a general-purpose aggregation building block, represented as an aggregation factory. The generality comes through the design intent in two ways:

1. *Parameterized computations.* Aggregation is an independent building block that can be plugged into other TFF modules designed to work with `tff.aggregators` to parameterize their necessary aggregation, such as `tff.learning.build_federated_averaging_process`.
1. *Aggregation composition.* An aggregation building block can be composed with other aggregation building blocks to create more complex composite aggregations.
"""