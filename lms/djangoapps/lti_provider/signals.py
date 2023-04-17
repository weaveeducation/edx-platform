"""
Signals handlers for the lti_provider Django app.
"""
from __future__ import absolute_import

from django.dispatch import receiver

from lms.djangoapps.grades.signals.signals import PROBLEM_WEIGHTED_SCORE_CHANGED
from .tasks import ScoresHandler


@receiver(PROBLEM_WEIGHTED_SCORE_CHANGED)
def score_changed_handler(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Consume signals that indicate score changes. See the definition of
    PROBLEM_WEIGHTED_SCORE_CHANGED for a description of the signal.
    """
    handler = ScoresHandler()
    handler.score_changed_handler(**kwargs)
