# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — small helpers for threads and widgets
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Helpers shared by the panels."""

import weakref


def post_when_done(post, future, method, *args):
    """When *future* finishes, call ``method(future, *args)`` on the Tk
    thread (through *post*).

    The method's object is held only weakly. A callback that captured the
    widget would keep it alive inside a worker thread's work item; if the
    widget had been closed meanwhile, the worker would be the one to free it
    and so finalise its Tk variables off the Tk thread, which Tk does not
    allow. A widget that is gone by the time the result arrives is skipped.
    """
    reference = weakref.WeakMethod(method)

    def relay(done):
        post(_invoke, reference, done, args)

    future.add_done_callback(relay)


def post_weak(post, method, *args):
    """Run ``method(*args)`` on the Tk thread through *post*, holding the
    method's object only weakly (see :func:`post_when_done`)."""
    post(_invoke_plain, weakref.WeakMethod(method), args)


def weak_notifier(post, method):
    """``notify(*args)``, safe to call from any thread, that runs
    ``method(*args)`` on the Tk thread without keeping the method's object
    alive (see :func:`post_when_done`). For worker threads that report
    several times or at the end."""
    reference = weakref.WeakMethod(method)

    def notify(*args):
        post(_invoke_plain, reference, args)

    return notify


def _invoke_plain(reference, args):
    method = reference()
    if method is not None:
        method(*args)


def _invoke(reference, done, args):
    method = reference()
    if method is not None:
        method(done, *args)
