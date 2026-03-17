# Datafiles

Datafiles is a bidirectional serialization library for Python [dataclasses](https://docs.python.org/3/library/dataclasses.html) to synchronizes objects to the filesystem using type annotations. It supports a variety of file formats with round-trip preservation of formatting and comments, where possible. Object changes are automatically saved to disk and only include the minimum data needed to restore each object.

Some common use cases include:

- Coercing user-editable files into the proper Python types
- Storing program configuration and state in version control
- Loading data fixtures for demonstration or testing purposes
- Synchronizing application state using file sharing services
- Prototyping data models agnostic of persistence backends

## Quick Start

Decorate a [type-annotated](https://docs.python.org/3/library/typing.html) class with a directory pattern to synchronize instances:

```python
from datafiles import datafile

@datafile("samples/{self.key}.yml")
class Sample:

    key: int
    name: str
    value: float = 0.0
```

By default, all member variables will be included in the serialized file except for those:

- Included in the directory pattern
- Set to default values

So, the following instantiation:

```python
>>> sample = Sample(42, "Widget")
```

produces `samples/42.yml` containing:

```yaml
name: Widget
```

and the following instantiation restores the object:

```python
>>> from datafiles import Missing
>>> sample = Sample(42, Missing)
>>> sample.name
Widget
```

---

# File Formats

Many formats are supported for serialization, but this project only uses YAML:

## YAML

By default, datafiles uses the [YAML language](https://yaml.org/) for serialization.
Any of the following file extensions will use this format:

- `.yml`
- `.yaml`
- (no extension)

Sample output:

```yaml
my_dict:
  value: 0
my_list:
  - value: 1
  - value: 2
my_bool: true
my_float: 1.23
my_int: 42
my_str: Hello, world!
```

Where possible, comments and whitespace are preserved in files.

---

# Utilities

The following functions exist to provide additional high-level functionality.

## `sync()`

This helper can be used to enable file synchronization on an arbitrary object:

```python
from dataclasses import dataclass

@dataclass
class InventoryItem:
    name: str
    unit_price: float
    quantity_on_hand: int = 0
```

by providing it a path or directory pattern:

```python
>>> from datafiles import sync
>>> item = InventoryItem("widget", 3)
>>> sync(item, "inventory/items/{self.name}.yml")
```

# Manager API

Object-relational mapping (ORM) methods are available on all model classes via the `objects` proxy. The following sections assume an empty filesystem and the following sample datafile definition:

```python
from datafiles import datafile

@datafile("my_models/{self.my_key}.yml")
class MyModel:

    my_key: str
    my_value: int = 0
```

Many of the following examples are also shown in [this notebook](https://github.com/jacebrowning/datafiles/blob/main/notebooks/manager_api.ipynb).

## `get()`

Instantiate an object from an existing file. If no matching file exist, or if any other problem occurs, an appropriate exception will be raised.

```python
>>> MyModel.objects.get("foobar")
Traceback (most recent call last):
  ...
FileNotFoundError: [Errno 2] No such file or directory: "foobar.yml"
```

```python
>>> m = MyModel("foobar", 42)
```

```python
>>> MyModel.objects.get("foobar")
MyModel(my_key="foobar", my_value=42)
```

## `get_or_none()`

Instantiate an object from an existing file or return `None` if no matching file exists:

```python
>>> MyModel.objects.get_or_none("foobar")
None
```

```python
>>> m = MyModel("foobar", 42)
```

```python
>>> MyModel.objects.get_or_none("foobar")
MyModel(my_key="foobar", my_value=42)
```

## `get_or_create()`

Instantiate an object from an existing file or create one if no matching file exists:

```python
>>> m = MyModel("foo", 42)
```

```python
>>> MyModel.objects.get_or_create("foo")
MyModel(my_key="foo", my_value=42)
```

```python
>>> MyModel.objects.get_or_create("bar")
MyModel(my_key="bar", my_value=0)
```

## `all()`

Iterate over all objects matching the pattern:

```python
>>> generator = MyModel.objects.all()
>>> list(generator)
[]
```

```python
>>> m1 = MyModel("foo")
>>> m2 = MyModel("bar", 42)
```

```python
>>> for m in MyModel.objects.all():
...     print(m)
...
MyModel(my_key="foo" my_value=0)
MyModel(my_key="bar", my_value=42)
```

Exclude objects from ever being loaded and returned with `_exclude`:

```python
>>> generator = MyModel.objects.all(_exclude="foo")
```

## `filter()`

Iterate all objects matching the pattern with additional required attribute values:

```python
>>> generator = MyModel.objects.filter(my_value=42)
>>> list(generator)
[MyModel(my_key="foo", my_value=42)]
```

Exclude objects from ever being loaded and returned with `_exclude`:

```python
>>> generator = MyModel.objects.filter(_exclude="foo")
```

Nested dataclass values can be queried using `__` as a delimiter:

```python
>>> generator = NestedModel.objects.filter(foo__bar__qux=42)
```

---

# Mapper API

Instances of datafile models have an additional `datafile` proxy to manually interact with the filesystem. The following sections assume an empty filesystem and use the following sample datafile definition:

```python
from datafiles import datafile

@datafile("my_models/{self.my_key}.yml", manual=True)
class MyModel:

    my_key: str
    my_value: int = 1
```

```python
>>> model = MyModel("foo")
```

Many of the following examples are also shown in [this notebook](https://github.com/jacebrowning/datafiles/blob/main/notebooks/mapper_api.ipynb).

## `path`

Get the full path to the mapped file:

```python
>>> model.datafile.path
PosixPath("/Projects/Demo/my_models/foo.yml")
```

## `exists`

Determine if the mapped file exists:

```python
>>> model.datafile.exists
False
```

_By default, the file is created automatically. Set `manual=True` to disable this behavior._

## `save()`

Manually save an object to the filesystem:

```python
>>> model.datafile.save()
```

_By default, this method is called automatically. Set `manual=True` to disable this behavior._

## `load()`

Manually load an object from the filesystem:

```python
>>> model.datafile.load()
```

_By default, this method is called automatically. Set `manual=True` to disable this behavior._

## `modified`

Determine if there are any unsynchronized changes on the filesystem:

```
$ echo "my_value: 42" > my_models/foo.yml
```

```python
>>> model.datafile.modified
True
```

## `data`

Access the parsed model attributes directly:

```python
>>> model.datafile.data
ordereddict([("my_value", 1)])
```

---

# Model API

A model is created by either extending the `Model` class or using the `datafile()` decorator.

## Decorator

Given this example dataclass:

```python
from dataclasses import dataclass

@dataclass
class Item:
    name: str
    count: int
    available: bool
```

Synchronization is enabled by adding the `@datafile(<pattern>)` decorator:

```python hl_lines="5"
from dataclasses import dataclass

from datafiles import datafile

@datafile("items/{self.name}.yml")
@dataclass
class Item:
    name: str
    count: int
    available: bool
```

or by replacing the `@dataclass` decorator entirely:

```python hl_lines="3"
from datafiles import datafile

@datafile("items/{self.name}.yml")
class Item:
    name: str
    count: int
    available: bool
```

### Filename

Instances of the class are synchronized to disk according to the `<pattern>` string:

```python
Item("abc")  # <=> items/abc.yml
Item("def")  # <=> items/def.yml
```

Filename patterns are relative to the file in which the model is defined unless `<pattern>` is an absolute path or explicitly relative to the current directory:

- Absolute path: `/tmp/items/{self.name}.yml`
- Relative to model's module: `items/{self.name}.yml`
- Relative to the current directory: `./items/{self.name}.yml`
- Relative to the user's home directory: `~/items/{self.name}.yml`

Attributes included in the filename pattern and those with default value are automatically excluded from serialization since these redundant values are not required to restore objects from disk.

### Options

The following options can be passed to the `@datafile()` decorator:

| Name       | Type   | Description                                                           | Default |
| ---------- | ------ | --------------------------------------------------------------------- | ------- |
| `manual`   | `bool` | Synchronize object and file changes manually.                         | `False` |
| `defaults` | `bool` | Include attributes with default values when serializing.              | `False` |
| `infer`    | `bool` | Automatically infer new attributes from the file.                     | `False` |

<sup>1</sup> _By default, synchronized attributes are inferred from the type annotations._

For example:

```python hl_lines="3 9"
from datafiles import datafile

@datafile("items/{self.name}.yml", manual=True, defaults=True)
class Item:
    name: str
    count: int
    available: bool

@datafile("config.yml", infer=True)
class Config:
    default_count: int = 42
```

---

# Builtin Types

When Python builtin types are used as type annotations they are automatically mapped to the corresponding type in the chosen file format. Any of these types will accept `None` as a value when made optional.

```python
from typing import Optional
```

## Booleans

| Type Annotation          | Python Value     | YAML Content    |
| ------------------------ | ---------------- | --------------- |
| `foobar: bool`           | `foobar = True`  | `foobar: true`  |
| `foobar: bool`           | `foobar = False` | `foobar: false` |
| `foobar: bool`           | `foobar = None`  | `foobar: false` |
| `foobar: Optional[bool]` | `foobar = False` | `foobar:`       |

## Integers

| Type Annotation         | Python Value    | YAML Content |
| ----------------------- | --------------- | ------------ |
| `foobar: int`           | `foobar = 42`   | `foobar: 42` |
| `foobar: int`           | `foobar = 1.23` | `foobar: 1`  |
| `foobar: int`           | `foobar = None` | `foobar: 0`  |
| `foobar: Optional[int]` | `foobar = None` | `foobar:`    |

## Floats

| Type Annotation           | Python Value    | YAML Content   |
| ------------------------- | --------------- | -------------- |
| `foobar: float`           | `foobar = 1.23` | `foobar: 1.23` |
| `foobar: float`           | `foobar = 42`   | `foobar: 42.0` |
| `foobar: float`           | `foobar = None` | `foobar: 0.0`  |
| `foobar: Optional[float]` | `foobar = None` | `foobar:`      |

## Strings

| Type Annotation         | Python Value               | YAML Content            |
| ----------------------- | -------------------------- | ----------------------- |
| `foobar: str`           | `foobar = "Hello, world!"` | `foobar: Hello, world!` |
| `foobar: str`           | `foobar = 42`              | `foobar: "42"`          |
| `foobar: str`           | `foobar = None`            | `foobar: ""`            |
| `foobar: Optional[str]` | `foobar = None`            | `foobar:`               |

---

# Container Types

Various container types are supported to defined collections of objects.

## Lists

The `List` annotation can be used to define a homogeneous collection of any other type.

```python
from typing import List, Optional
```

| Type Annotation               | Python Value      | YAML Content                               |
| ----------------------------- | ----------------- | ------------------------------------------ |
| `foobar: List[int]`           | `foobar = []`     | `foobar:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`-`   |
| `foobar: List[int]`           | `foobar = [1.23]` | `foobar:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`- 1` |
| `foobar: List[int]`           | `foobar = None`   | `foobar:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`-`   |
| `foobar: Optional[List[int]]` | `foobar = None`   | `foobar:`                                  |

## Sets

The `Set` annotation can be used to define a homogeneous collection of unique elements of any other type.

```python
from typing import Set, Optional
```

| Type Annotation              | Python Value      | YAML Content                               |
| ---------------------------- | ----------------- | ------------------------------------------ |
| `foobar: Set[int]`           | `foobar = []`     | `foobar:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`-`   |
| `foobar: Set[int]`           | `foobar = [1.23]` | `foobar:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`- 1` |
| `foobar: Set[int]`           | `foobar = None`   | `foobar:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`-`   |
| `foobar: Optional[Set[int]]` | `foobar = None`   | `foobar:`                                  |

## Dictionaries

The `Dict` annotation can be used to define a loose mapping of multiple types.

```python
from typing import Dict, Optional
```

| Type Annotation                    | Python Value         | YAML Content                                 |
| ---------------------------------- | -------------------- | -------------------------------------------- |
| `foobar: Dict[str, int]`           | `foobar = {}`        | `foobar: {}`                                 |
| `foobar: Dict[str, int]`           | `foobar = {"a": 42}` | `foobar:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`a: 42` |
| `foobar: Dict[str, int]`           | `foobar = None`      | `foobar: {}`                                 |
| `foobar: Optional[Dict[str, int]]` | `foobar = None`      | `foobar:`                                    |

_⚠ Schema enforcement is not available with the `Dict` annotation._

## Dataclasses

Other dataclasses can serve as the annotation for an attribute to create nested structure:

```python hl_lines="14"
from dataclasses import dataclass

from datafiles import datafile


@dataclass
class Nested:
    qux: str


@datafile("sample.yml")
class Sample:
    foo: int
    bar: Nested
```

which can be constructed like so:

```python
sample = Sample(42, Nested("Hello, world!"))
```

to save this `sample.yml` file:

```yaml
foo: 42
bar:
  qux: Hello, world!
```

For convenience, `@datafile` can also be used in place of `@dataclass` to minimize the number of imports:

```python hl_lines="4"
from datafiles import datafile


@datafile
class Nested:
    qux: str
```

---

# Extended Types

For convenience, additional types are defined to handle common scenarios.

## Numbers

The `Number` converter should be used for values that can be both integers or floats, but should not be coerced into either type during serialization.

```python
from typing import Optional

from datafiles.converters import Number
```

| Type Annotation            | Python Value    | YAML Content   |
| -------------------------- | --------------- | -------------- |
| `foobar: Number`           | `foobar = 42`   | `foobar: 42`   |
| `foobar: Number`           | `foobar = 1.23` | `foobar: 1.23` |
| `foobar: Number`           | `foobar = None` | `foobar: 0.0`  |
| `foobar: Optional[Number]` | `foobar = None` | `foobar:`      |

## Text

The `Text` converter should be used for strings that contain lines of text, which are optimally serialized across multiple lines in a file.

```python
from typing import Optional

from datafiles.converters import Text
```

| Type Annotation          | Python Value                 | YAML Content                                                                       |
| ------------------------ | ---------------------------- | ---------------------------------------------------------------------------------- |
| `foobar: Text`           | `foobar = "Hello, world!"`   | `foobar: Hello, world!`                                                            |
| `foobar: Text`           | `foobar = "First
Second
"` | `foobar: |`<br>&nbsp;&nbsp;&nbsp;&nbsp;`First`<br>&nbsp;&nbsp;&nbsp;&nbsp;`Second` |
| `foobar: Text`           | `foobar = None`              | `foobar: ""`                                                                       |
| `foobar: Optional[Text]` | `foobar = None`              | `foobar:`                                                                          |
