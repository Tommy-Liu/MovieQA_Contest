import tensorflow as tf

def int64_feature(value):
  """Wrapper for inserting an int64 Feature into a SequenceExample proto."""
  if not isinstance(value, (tuple, list)):
      value = [value]
  return tf.train.Feature(int64_list=tf.train.Int64List(value=value))


def bytes_feature(value):
  """Wrapper for inserting a bytes Feature into a SequenceExample proto."""
  return tf.train.Feature(bytes_list=tf.train.BytesList(value=[str(value)]))


def int64_feature_list(values):
  """Wrapper for inserting an int64 FeatureList into a SequenceExample proto."""
  return tf.train.FeatureList(feature=[_int64_feature(v) for v in values])


def bytes_feature_list(values):
  """Wrapper for inserting a bytes FeatureList into a SequenceExample proto."""
  return tf.train.FeatureList(feature=[_bytes_feature(v) for v in values])

def float_feature(value):
    if not isinstance(value, (tuple, list)):
        value = [value]
    return tf.train.Feature(float_list=tf.train.FloatList(value=value))

def float_feature_list(values):
    return tf.train.FeatureList(feature=[_float_feature(v) for v in values])
