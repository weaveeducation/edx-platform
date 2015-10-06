from django.conf import settings
from django.template.base import TemplateSyntaxError, Library, Node, TextNode,\
    token_kwargs, Variable, TemplateDoesNotExist
from django.template.loader import get_template
from django.template.loader_tags import BaseIncludeNode, IncludeNode, ConstantIncludeNode
from django.utils.safestring import mark_safe

register = Library()


class OptionalConstantIncludeNode(ConstantIncludeNode):
    def __init__(self, template_path, *args, **kwargs):
        # Note that this is calling super() on ConstantIncludeNode,
        # so it's calling the __init__() method of BaseIncludeNode.
        # It is *not* calling the __init__() method of ConstantIncludeNode itself.
        super(ConstantIncludeNode, self).__init__(*args, **kwargs)
        # The logic in the __init__() method of ConstantIncludeNode is
        # reproduced here, slightly altered.
        try:
            t = get_template(template_path)
            self.template = t
        except TemplateDoesNotExist:  # this line is new
            self.template = None      # this line is new
        except:
            if settings.TEMPLATE_DEBUG:
                raise
            self.template = None

    def render(self, context):
        if not self.template:
            return ''
        try:
            return self.render_template(self.template, context)
        except TemplateDoesNotExist:
            return ''


class OptionalIncludeNode(IncludeNode):
    def render(self, context):
        try:
            template_name = self.template_name.resolve(context)
            template = get_template(template_name)
            return self.render_template(template, context)
        except TemplateDoesNotExist:  # this line is new
            return ''                 # this line is new
        except:
            if settings.TEMPLATE_DEBUG:
                raise
            return ''


@register.tag('optional_include')
def do_include(parser, token):
    """
    Loads a template and renders it with the current context, but don't throw
    an error if the template doesn't exist. You can pass additional context
    using keyword arguments.

    Example::

        {% optional_include "foo/some_include" %}
        {% optional_include "foo/some_include" with bar="BAZZ!" baz="BING!" %}

    Use the ``only`` argument to exclude the current context when rendering
    the included template::

        {% optional_include "foo/some_include" only %}
        {% optional_include "foo/some_include" with bar="1" only %}
    """
    bits = token.split_contents()
    if len(bits) < 2:
        msg = (
            "%r tag takes at least one argument: the name of the template "
            "to be optionally included."
        ) % bits[0]
        raise TemplateSyntaxError(msg)
    options = {}
    remaining_bits = bits[2:]
    while remaining_bits:
        option = remaining_bits.pop(0)
        if option in options:
            raise TemplateSyntaxError('The %r option was specified more '
                                      'than once.' % option)
        if option == 'with':
            value = token_kwargs(remaining_bits, parser, support_legacy=False)
            if not value:
                raise TemplateSyntaxError('"with" in %r tag needs at least '
                                          'one keyword argument.' % bits[0])
        elif option == 'only':
            value = True
        else:
            raise TemplateSyntaxError('Unknown argument for %r tag: %r.' %
                                      (bits[0], option))
        options[option] = value
    isolated_context = options.get('only', False)
    namemap = options.get('with', {})
    path = bits[1]
    if path[0] in ('"', "'") and path[-1] == path[0]:
        return OptionalConstantIncludeNode(
            path[1:-1], extra_context=namemap, isolated_context=isolated_context,
        )
    return OptionalIncludeNode(
        parser.compile_filter(bits[1]), extra_context=namemap,
        isolated_context=isolated_context,
    )
