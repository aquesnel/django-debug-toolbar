from os.path import normpath
from pprint import pformat

from django import http
from django.conf import settings
from django.core.signals import request_started
from django.dispatch import Signal
from django.template.context import get_standard_processors, Context
from django.template.loader import render_to_string
from django.test.signals import template_rendered
from django.utils.translation import ugettext_lazy as _
from debug_toolbar.panels import DebugPanel

# Code taken and adapted from Simon Willison and Django Snippets:
# http://www.djangosnippets.org/snippets/766/

# Monkeypatch instrumented test renderer from django.test.utils - we could use
# django.test.utils.setup_test_environment for this but that would also set up
# e-mail interception, which we don't want
from django.test.utils import instrumented_test_render
from django.template import Template

if not hasattr(Template, '_render'): # Django < 1.2
    if Template.render != instrumented_test_render:
        Template.original_render = Template.render
        Template.render = instrumented_test_render
else:
    if Template._render != instrumented_test_render:
        Template.original_render = Template._render
        Template._render = instrumented_test_render

# MONSTER monkey-patch
old_template_init = Template.__init__
def new_template_init(self, template_string, origin=None, name='<Unknown Template>'):
    old_template_init(self, template_string, origin, name)
    self.origin = origin
Template.__init__ = new_template_init

class TemplateDebugPanel(DebugPanel):
    """
    A panel that lists all templates used during processing of a response.
    """
    name = 'Template'
    has_content = True

    def __init__(self, *args, **kwargs):
        super(self.__class__, self).__init__(*args, **kwargs)
        self.templates = []
        template_rendered.connect(self._store_template_info)

    def _store_template_info(self, sender, **kwargs):
        self.templates.append(kwargs)

    def nav_title(self):
        return _('Templates')

    def title(self):
        num_templates = len([t for t in self.templates
            if not t['template'].name.startswith('debug_toolbar/')])
        return _('Templates (%(num_templates)s rendered)') % {'num_templates': num_templates}

    def url(self):
        return ''

    def process_request(self, request):
        self.request = request

    def content(self):
        context_processors = dict(
            [
                ("%s.%s" % (k.__module__, k.__name__),
                    pformat(k(self.request))) for k in get_standard_processors()
            ]
        )
        template_context = []
        for template_data in self.templates:
            info = {}
            # Clean up some info about templates
            template = template_data.get('template', None)
            # Skip templates that we are generating through the debug toolbar.
            if template.name.startswith('debug_toolbar/'):
                continue
            if template.origin and template.origin.name:
                template.origin_name = template.origin.name
            else:
                template.origin_name = 'No origin'
            info['template'] = template
            # Clean up context for better readability
            if getattr(settings, 'DEBUG_TOOLBAR_CONFIG', {}).get('SHOW_TEMPLATE_CONTEXT', True):
                context_data = template_data.get('context', Context())

                def flatten_context(context_data, depth = 0):
                    if depth >= 10:
                        return  {}
                    
                    flat_context = {}
                    # Read the stack of dictionaries in reverse order so that 
                    # the context layers on the top of the stack overwrite 
                    # values in context layers at the botom of the stack. 
                    for context_layer in context_data.dicts[::-1]:
                        if isinstance(context_layer, Context):
                            # for Context and RequestContext objects that may be 
                            # included in the context_data.dicts stack, we just 
                            # want to flatten all the dicts in that context layer. 
                            flat_context.update(flatten_context(context_layer, depth + 1))
                        elif hasattr(context_layer, 'items'):
                            flat_context.update(context_layer)
                        else:
                            raise NotImplementedError("Received a context_layer that is not either a Context or a dictionary like object (supports the 'items' method)")
                            
                    return flat_context
                final_context = flatten_context(context_data)
                
                # Replace any request elements - they have a large
                # unicode representation and the request data is
                # already made available from the Request Vars panel.
                if final_context.has_key('request'):
                    final_context['request'] = '<<request>> (see the Request Vars panel)'
                # Replace the debugging sql_queries element. The SQL
                # data is already made available from the SQL panel.
                if final_context.has_key('sql_queries'):
                    final_context['sql_queries'] = '<<sql_queries>> (see the SQL panel)'
                # Replace LANGUAGES, which is available in i18n context processor
                if final_context.has_key('LANGUAGES'):
                    final_context['LANGUAGES'] = '<<languages>> (see the i18n context processor)'
                
                try:
                    info['context'] = pformat(final_context)
                except UnicodeEncodeError:
                    info['context'] = 'Unicode encoding error for template contextes'
                                
            template_context.append(info)

        context = self.context.copy()
        context.update({
            'templates': template_context,
            'template_dirs': [normpath(x) for x in settings.TEMPLATE_DIRS],
            'context_processors': context_processors,
        })

        return render_to_string('debug_toolbar/panels/templates.html', context)
