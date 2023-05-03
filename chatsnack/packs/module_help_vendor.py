import inspect
import importlib
import sys

def get_module_inspection_report(module_name, visited=None):
    if visited is None:
        visited = set()
    if module_name in visited:
        return []

    module = importlib.import_module(module_name)
    visited.add(module_name)
    output = []

    output.append(f"\nModule: {module.__name__}")
    docstring = get_docstring(module)
    if docstring:
        output.append(f'"""\n{docstring}"""')

    for name, obj in inspect.getmembers(module):
        breaker = False
        for nam in ['_','Path', 'datetime', 'IO', 'datafile']:
            if name.startswith(nam):
                breaker = True
                break
        if breaker:
            continue
        for nam in ['aiwrapper','asynchelpers', 'datetime', 'IO', 'datafile']:
            if name in nam:
                breaker = True
                break
        if breaker:
            continue

        if inspect.ismodule(obj):
            if obj.__name__ not in visited and obj.__name__.startswith(module_name):
                output.extend([get_module_inspection_report(obj.__name__, visited)])
        elif not (inspect.isbuiltin(obj) or (hasattr(obj, '__module__') and obj.__module__ in sys.builtin_module_names)):
            if inspect.isclass(obj):
                output.extend(_process_class(obj))
            elif inspect.isfunction(obj):
                output.extend(_process_function(obj))

    return "\n".join(output)

def _process_class(cls):
    if cls.__module__ in sys.builtin_module_names:
        return []

    output = []

    output.append(f"Class: {cls.__name__}")
    docstring = get_docstring(cls)
    if docstring:
        output.append(f'"""{docstring}"""')

    methods_output = []
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith('_'):
            continue

        methods_output.extend(_process_function(method, cls))

    if methods_output:
        output.append("Methods:")
        output.extend(methods_output)

    return output

def _process_function(func, cls=None):
    output = []

    signature = inspect.signature(func)
    params = ', '.join(f"{name}{': ' + param.annotation.__name__ if (param.annotation is not inspect.Parameter.empty and hasattr(param.annotation, '__name__')) else ''}" for name, param in signature.parameters.items())


    func_name = f"{cls.__name__}.{func.__name__}" if cls else func.__name__

    output.append(f"\n{func_name}({params})")
    docstring = get_docstring(func)
    if docstring:
        output.append(f'"""\n{docstring}"""')

    return output

def get_docstring(obj):
    docstring = inspect.getdoc(obj)
    if docstring and "⭐" in docstring:
        return f"⭐ {docstring.replace('⭐', '')}"
    return docstring
