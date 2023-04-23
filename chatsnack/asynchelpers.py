import asyncio
import string

from loguru import logger

class _AsyncFormatter(string.Formatter):
    async def async_expand_field(self, field, args, kwargs):
        if "." in field:
            obj, method = field.split(".", 1)
            if obj in kwargs:
                obj_instance = kwargs[obj]
                if hasattr(obj_instance, method):
                    method_instance = getattr(obj_instance, method)
                    if asyncio.iscoroutinefunction(method_instance):
                        return await method_instance()
                    else:
                        return method_instance() if callable(method_instance) else method_instance
        value, _ = super().get_field(field, args, kwargs)
        return value

    async def async_format(self, format_string, *args, **kwargs):
        coros = []
        parsed_format = list(self.parse(format_string))

        for literal_text, field_name, format_spec, conversion in parsed_format:
            if field_name:
                coro = self.async_expand_field(field_name, args, kwargs)
                coros.append(coro)

        expanded_fields = await asyncio.gather(*coros)
        expanded_iter = iter(expanded_fields)

        return ''.join([
            literal_text + (str(next(expanded_iter)) if field_name else '')
            for literal_text, field_name, format_spec, conversion in parsed_format
        ])
    
# instance to use
aformatter = _AsyncFormatter()
