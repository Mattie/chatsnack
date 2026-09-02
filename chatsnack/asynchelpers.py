import asyncio
import string

from loguru import logger


async def _gather_cancel_on_error(*awaitables):
    """Gather concurrent work without letting siblings outlive a failure."""

    tasks = [asyncio.ensure_future(awaitable) for awaitable in awaitables]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class _AsyncFormatter(string.Formatter):
    async def async_expand_field(self, field, args, kwargs):
        if "." in field:
            obj, method = field.split(".", 1)
            if obj in kwargs:
                obj_instance = kwargs[obj]
                field_resolver = getattr(
                    type(obj_instance),
                    "_chatsnack_expand_field",
                    None,
                )
                if field_resolver is not None:
                    return await field_resolver(obj_instance, method)
                if hasattr(obj_instance, method):
                    method_instance = getattr(obj_instance, method)
                    if asyncio.iscoroutinefunction(method_instance):
                        return await method_instance()
                    else:
                        return method_instance() if callable(method_instance) else method_instance
        value, _ = super().get_field(field, args, kwargs)
        return value

    async def async_format(self, format_string, *args, **kwargs):
        return await self._async_format_fields(
            format_string,
            kwargs,
            args,
            asyncio.gather,
        )

    async def async_format_mapping(self, format_string, variables, args=()):
        """Format with variables passed as data instead of method keywords."""

        return await self._async_format_fields(
            format_string,
            variables,
            args,
            _gather_cancel_on_error,
        )

    async def _async_format_fields(
        self,
        format_string,
        variables,
        args,
        gather_fields,
    ):
        """Format fields with the sibling-failure policy chosen by the caller."""

        coros = []
        parsed_format = list(self.parse(format_string))

        for literal_text, field_name, format_spec, conversion in parsed_format:
            if field_name:
                coro = self.async_expand_field(field_name, args, variables)
                coros.append(coro)

        expanded_fields = await gather_fields(*coros)
        expanded_iter = iter(expanded_fields)

        return ''.join([
            literal_text + (str(next(expanded_iter)) if field_name else '')
            for literal_text, field_name, format_spec, conversion in parsed_format
        ])
    
# instance to use
aformatter = _AsyncFormatter()
