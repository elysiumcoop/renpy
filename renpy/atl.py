# Copyright 2004-2009 PyTom <pytom@bishoujo.us>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import renpy
import random

def compiling(loc):
    file, number = loc

    renpy.game.exception_info = "Compiling ATL code at %s:%d" % (file, number)

def executing(loc):
    file, number = loc
    
    renpy.game.exception_info = "Executing ATL code at %s:%d" % (file, number)


# A map from the name of a time warp function to the function itself.
warpers = { }

def atl_warper(f):
    name = f.func_name
    warpers[name] = f
    return f
    
# The pause warper is used internally when no other warper is
# specified.
@atl_warper
def pause(t):
    if t < 1.0:
        return 0.0
    else:
        return 1.0

# A dictionary giving property names and the corresponding default
# values.
PROPERTIES = set([
        "pos",
        "xpos",
        "ypos",
        "xanchor",
        "yanchor",
        "xalign",
        "yalign",
        "rotate",
        "xzoom",
        "yzoom",
        "zoom",
        "alpha",
        "around",
        "angle",
        "radius",
        "alignaround",
        "alignangle",
        "alignradius",
    ])

def interpolate(t, a, b):
    """
    Linearly interpolate the arguments. 
    """

    if t >= 1.0:
        return b
    
    # Recurse into tuples.
    if isinstance(b, tuple):
        return tuple(interpolate(t, i, j) for i, j in zip(a, b))

    # Deal with strings.
    elif isinstance(b, (str, unicode)):
        if t >= 1.0:
            return a
        else:
            return b

    # Interpolate everything else.
    else:
        return type(b)(a + t * (b - a))

# Interpolate the value of a spline. This code is based on Aenakume's code,
# from 00splines.rpy.
def interpolate_spline(t, spline):

    if isinstance(spline[-1], tuple):
        return tuple(interpolate_spline(t, i) for i in zip(*spline))
        
    if len(spline) == 2:
        t_p = 1.0 - t        

        rv = t_p * spline[0] + t * spline[-1]

    elif len(spline) == 3:
        t_pp = (1.0 - t)**2
        t_p = 2 * t * (1.0 - t)
        t2 = t**2
        
        rv = t_pp * spline[0] + t_p * spline[1] + t2 * spline[2]

    elif len(spline) == 4:

        t_ppp = (1.0 - t)**3
        t_pp = 3 * t * (1.0 - t)**2
        t_p = 3 * t**2 * (1.0 - t)
        t3 = t**3
        
        rv = t_ppp * spline[0] + t_pp * spline[1] + t_p * spline[2] + t3 * spline[3]

    else:
        raise Exception("ATL can't interpolate splines of length %d." % len(spline))

    return type(spline[-1])(rv)
    

# This is the context used when compiling an ATL statement. It stores the
# scopes that are used to evaluate the various expressions in the statement,
# and has a method to do the evaluation and return a result.
class Context(object):
    def __init__(self, context):
        self.context = context

    def eval(self, expr):
        return eval(expr, renpy.store.__dict__, self.context)
    
    
# This is intended to be subclassed by ATLTransform. It takes care of
# managing ATL execution, which allows ATLTransform itself to not care
# much about the contents of this file.
class TransformBase(renpy.object.Object):

    def __init__(self, atl, context):

        # The raw code that makes up this ATL statement.
        self.atl = atl

        # The context in which execution occurs.
        self.context = Context(context)
        
        # The code after it has been compiled into a block.
        self.block = None

        # The properties of the block, if it contains only an
        # Interpolation.
        self.properties = None

        # The state of the statement we are executing.
        self.atl_state = None

        # Are we done?
        self.done = False
        
    # Compiles self.atl into self.block, and then update the rest of
    # the variables.
    def compile(self):

        old_exception_info = renpy.game.exception_info
        
        self.block = self.atl.compile(self.context)

        if len(self.block.statements) == 1 \
                and isinstance(self.block.statements[0], Interpolation):

            interp = self.block.statements[0]

            if interp.duration == 0 and interp.properties:
                self.properties = interp.properties[:]

        renpy.game.exception_info = old_exception_info
                    
    def execute(self, trans, st, at):
        if self.done:
            return None

        event = None
        
        if not self.block:
            self.compile()
        
        old_exception_info = renpy.game.exception_info

        action, arg, pause = self.block.execute(trans.state, st, self.atl_state, event)

        renpy.game.exception_info = old_exception_info

        if action == "continue":
            self.atl_state = arg
        else:
            self.done = True

        return pause

    def predict(self, callback):
        self.atl.predict(self.context, callback)
        
    def visit(self):
        if not self.block:
            self.compile()

        return self.block.visit()
        
    
# The base class for raw ATL statements.
class RawStatement(renpy.object.Object):

    # Compiles this RawStatement into a Statement, by using ctx to
    # evaluate expressions as necessary.
    def compile(self, ctx):
        raise Exception("Compile not implemented.")

    # Predicts the images used by this statement.
    def predict(self, ctx, callback):
        return
    

# The base class for compiled ATL Statements.
class Statement(renpy.object.Object):

    # trans is the transform we're working on.
    # st is the time since this statement started executing.
    # state is the state stored by this statement, or None if
    # we've just started executing this statement.
    # event is an event we're triggering.
    #
    # "continue", state, pause - Causes this statement to execute
    # again, with the given state passed in the second time around.
    #
    # 
    # "next", timeleft, pause - Causes the next statement to execute,
    # with timeleft being the amount of time left after this statement
    # finished.
    #
    # "event", (name, timeleft), pause - Causes an event to be reported,
    # and control to head up to the event handler.
    #
    # "repeat", (count, timeleft), pause - Causes the repeat behavior
    # to occur.
    #
    # As the Repeat statement can only appear in a block, only Block
    # needs to deal with the repeat behavior.
    #
    # Pause is the amount of time until execute should be called again,
    # or None if there's no need to call execute ever again.
    def execute(self, trans, st, state, event):
        raise Exception("Not implemented.")

    # Return a list of displayable children.
    def visit(self):
        return [ ]
        
# This represents a Raw ATL block.
class RawBlock(RawStatement):

    def __init__(self, loc, statements):

        self.loc = loc
        
        # A list of RawStatements in this block.
        self.statements = statements

    def compile(self, ctx):
        compiling(self.loc)

        statements = [ i.compile(ctx) for i in self.statements ]

        return Block(self.loc, statements)

    def predict(self, ctx, callback):
        for i in self.statements:
            i.predict(ctx, callback)
    
    
# A compiled ATL block. 
class Block(Statement):
    def __init__(self, loc, statements):

        self.loc = loc
        
        # A list of statements in the block.
        self.statements = statements

        # The start times of various statements.
        self.times = [ ]
        
        for i, s in enumerate(statements):
            if isinstance(s, Time):
                self.times.append((s.time, i + 1))

        self.times.sort()
        
    def execute(self, trans, st, state, event):

        executing(self.loc)
        
        # Unpack the state.
        if state is not None:
            index, start, repeats, times, child_state = state
        else:
            index, start, repeats, times, child_state = 0, 0, 0, self.times[:], None

        # What we might be returning.
        action = "continue"
        arg = None
        pause = None
        
        while action == "continue":

            # Target is the time we're willing to execute to.
            # Max_pause is how long we'll wait before executing again.

            # If we have times queued up, then use them to inform target
            # and time.
            if times:
                time, tindex = times[0]
                target = min(time, st)
                max_pause = time - target

            # Otherwise, take the defaults.
            else:
                target = st
                max_pause = 1000

            for i in range(0, 64):

                # If we've hit the last statement, it's the end of
                # this block.
                if index >= len(self.statements):
                    return "next", target - start, None

                try:

                   # Find the statement and try to run it.
                    stmt = self.statements[index]
                    action, arg, pause = stmt.execute(trans, target - start, child_state, event)

                    # On continue, persist our state.
                    if action == "continue":
                        if pause is None:
                            pause = max_pause
                            
                        action, arg, pause = "continue", (index, start, repeats, times, arg), min(max_pause, pause)
                        break

                    elif action == "event":
                        return action, arg, pause
                    
                    # On next, advance to the next statement in the block.
                    elif action == "next":
                        index += 1
                        start = target - arg
                        child_state = None

                    # On repeat, either terminate the block, or go to
                    # the first statement.
                    elif action == "repeat":
                        count, arg = arg
                        repeats += 1

                        if count is not None and repeats >= count:
                            return "next", arg, None
                        else:
                            index = 0
                            start = target - arg
                            child_state = None

                except:
                    # If an exception occurs when dealing with a statment,
                    # advance to the next statement.

                    # if renpy.config.debug:
                    #     raise

                    raise

                    index += 1
                    start = target
                    child_state = None

            else:

                if renpy.config.debug:
                    raise Exception("ATL Block probably in infinite loop.")

                return "continue", (index, st, repeats, times, child_state), 0

            if self.times:
                time, tindex = times[0]
                if time <= target:
                    times.pop(0)
                    
                    index = tindex
                    start = time
                    child_state = None

                    continue

            return action, arg, pause

    def visit(self):
        return [ j for i in self.statements for j in i.visit() ]
            
# This can become one of four things:
#
# - A pause.
# - An interpolation (which optionally can also reference other
# blocks, as long as they're not time-dependent, and have the same
# arity as the interpolation).
# - A call to another block.
# - A command to change the image, perhaps with a transition.
#
# We won't decide which it is until runtime, as we need the
# values of the variables here.
class RawMultipurpose(RawStatement):

    def __init__(self, loc):

        self.loc = loc
        
        self.warper = None
        self.duration = None
        self.properties = [ ]
        self.expressions = [ ]
        self.splines = [ ]
        self.revolution = None
        self.circles = "0"
        
    def add_warper(self, name, duration):
        self.warper = name
        self.duration = duration
        
    def add_property(self, name, exprs):
        self.properties.append((name, exprs))

    def add_expression(self, expr, with_clause):
        self.expressions.append((expr, with_clause))

    def add_revolution(self, revolution):
        self.revolution = revolution
        
    def add_circles(self, circles):
        self.circles = circles

    def add_spline(self, name, exprs):
        self.splines.append((name, exprs))
        
    def compile(self, ctx):

        compiling(self.loc)
        
        # Figure out what kind of statement we have. If there's no
        # interpolator, and no properties, than we have either a
        # call, or a child statement.
        if (self.warper is None and
            not self.properties and
            not self.splines and
            len(self.expressions) == 1):

            expr, withexpr = self.expressions[0]

            child = ctx.eval(expr)
            if withexpr:
                transition = ctx.eval(withexpr)
            else:
                transition = None

            if isinstance(child, (int, float)):
                return Interpolation(self.loc, "pause", child, [ ])
                
            if isinstance(child, TransformBase):
                child.compile()
                return child.block

            else:
                return Child(self.loc, child, transition)

        compiling(self.loc)

        # Otherwise, we probably have an interpolation statement.
        warper = self.warper or "pause"

        if warper not in warpers:
            raise Exception("ATL Warper %s is unknown at runtime." % warper)

        properties = [ ]

        for name, expr in self.properties:
            if name not in PROPERTIES:
                raise Exception("ATL Property %s is unknown at runtime." % property)

            value = ctx.eval(expr)
            properties.append((name, value))

        splines = [ ]
            
        for name, exprs in self.splines:
            if name not in PROPERTIES:
                raise Exception("ATL Property %s is unknown at runtime." % property)

            values = [ ctx.eval(i) for i in exprs ]

            splines.append((name, values))
            
        for expr, with_ in self.expressions:
            try:
                value = ctx.eval(expr)
            except:
                raise Exception("Could not evaluate expression %r when compiling ATL." % expr)

            if not isinstance(value, TransformBase):
                raise Exception("Expression %r is not an ATL transform, and so cannot be included in an ATL interpolation." % expr)

            value.compile()

            if value.properties is None:
                raise Exception("ATL transform %r is too complicated to be included in interpolation." % expr)


            properties.extend(value.properties)

        duration = ctx.eval(self.duration)
        circles = ctx.eval(self.circles)

        return Interpolation(self.loc, warper, duration, properties, self.revolution, circles, splines)
            
    def predict(self, ctx, callback):

        for i, j in self.expressions:
            
            try:
                i = ctx.eval(i)
            except:
                continue

            if isinstance(i, TransformBase):
                i.atl.predict(ctx, callback)
                return

            try:
                i = renpy.easy.displayable(i)
            except:
                continue

            if isinstance(i, renpy.display.core.Displayable):
                i.predict(callback)

                
            
# This changes the child of this statement, optionally with a transition.
class Child(Statement):

    def __init__(self, loc, child, transition):
        self.loc = loc

        self.child = renpy.easy.displayable(child)
        self.transition = transition

    def execute(self, trans, st, state, event):

        executing(self.loc)
        
        old_child = trans.raw_child
        
        if old_child is not None and self.transition is not None:
            trans.child = self.transition(old_widget=old_child,
                                          new_widget=self.child)
        else:
            trans.child = self.child

        trans.raw_child = self.child

        return "next", st, None

    def visit(self):
        return [ self.child ]
    
        
# This causes interpolation to occur.
class Interpolation(Statement):

    def __init__(self, loc, warper, duration, properties, revolution, circles, splines):
        self.loc = loc
        self.warper = warper
        self.duration = duration
        self.properties = properties
        self.splines = splines
        
        # The direction we revolve in: cw, ccw, or None.
        self.revolution = revolution

        # The number of complete circles we make.
        self.circles = circles
        
    def execute(self, trans, st, state, event):

        executing(self.loc)
        
        warper = warpers[self.warper]
        
        if self.duration:
            complete = min(1.0, st / self.duration)
        else:
            complete = 1.0

        complete = warper(complete)

        if state is None:

            # Create a new transform state, and apply the property
            # changes to it.
            newtrans = renpy.display.motion.TransformState()
            newtrans.take_state(trans)

            for k, v in self.properties:
                setattr(newtrans, k, v)

            # Now, the things we change linearly are in the difference
            # between the new and old states.
            linear = trans.diff(newtrans)
            revolution = None
            splines = [ ]
            
            # Clockwise revolution.
            if self.revolution is not None:

                # Remove various irrelevant motions.
                for i in [ 'xpos', 'ypos',
                           'xanchor', 'yanchor',
                           'xaround', 'yaround',
                           'xanchoraround', 'yanchoraround',
                           ]:

                    linear.pop(i, None)

                if newtrans.xaround is not None:

                    # Ensure we rotate around the new point.
                    trans.xaround = newtrans.xaround
                    trans.yaround = newtrans.yaround
                    trans.xanchoraround = newtrans.xanchoraround
                    trans.yanchoraround = newtrans.yanchoraround

                    # Get the start and end angles and radii.
                    startangle = trans.angle
                    endangle = newtrans.angle
                    startradius = trans.radius
                    endradius = newtrans.radius

                    # Make sure the revolution is in the appropriate direction,
                    # and contains an appropriate number of circles.

                    if self.revolution == "clockwise":
                        if endangle < startangle:
                            startangle -= 360

                        startangle -= self.circles * 360

                    elif self.revolution == "counterclockwise":
                        if endangle > startangle:
                            startangle += 360

                        startangle += self.circles * 360
                        
                    # Store the revolution.
                    revolution = (startangle, endangle, startradius, endradius)

            # Figure out the splines.
            for name, values in self.splines:
                splines.append((name, [ getattr(trans, name) ] + values))
                    
            state = (linear, revolution, splines)

        else:
            linear, revolution, splines = state
            
        # Linearly interpolate between the things in linear.
        for k, (old, new) in linear.iteritems():
            value = interpolate(complete, old, new)
            setattr(trans, k, value)

        # Handle the revolution.
        if revolution is not None:
            startangle, endangle, startradius, endradius = revolution
            trans.angle = interpolate(complete, startangle, endangle)
            trans.radius = interpolate(complete, startradius, endradius)

        # Handle any splines we might have.
        for name, values in splines:
            value = interpolate_spline(complete, values)
            setattr(trans, name, value)
            
        if st >= self.duration:
            return "next", st - self.duration, None
        else:
            if not self.properties and not self.revolution and not self.splines:
                return "continue", state, self.duration - st
            else:            
                return "continue", state, 0


# Implementation of the repeat statement.
class RawRepeat(RawStatement):

    def __init__(self, loc, repeats):
        self.loc = loc
        self.repeats = repeats

    def compile(self, ctx):

        compiling(self.loc)

        repeats = self.repeats

        if repeats is not None:
            repeats = ctx.eval(repeats)
            
        return Repeat(self.loc, repeats)

class Repeat(Statement):

    def __init__(self, loc, repeats):
        self.loc = loc
        self.repeats = repeats

    def execute(self, trans, st, state, event):
        return "repeat", (self.repeats, st), 0


# Parallel statement.

class RawParallel(RawStatement):

    def __init__(self, loc, block):
        self.loc = loc
        self.blocks = [ block ]

    def compile(self, ctx):
        return Parallel(self.loc, [i.compile(ctx) for i in self.blocks])

    def predict(self, ctx, callback):
        for i in self.blocks:
            i.predict(ctx, callback)
    
        
class Parallel(Statement):

    def __init__(self, loc, blocks):
        self.loc = loc
        self.blocks = blocks

    def execute(self, trans, st, state, event):

        executing(self.loc)
        
        if state is None:
            state = [ (i, None) for i in self.blocks ]

        # The amount of time left after finishing this block.
        left = [ ]

        # The duration of the pause.
        pauses = [ ]

        # The new state structure.
        newstate = [ ]
        
        for i, istate in state:
            
            action, arg, pause = i.execute(trans, st, istate, event)

            if pause is not None:
                pauses.append(pause)

            if action == "continue":
                newstate.append((i, arg))
            elif action == "next":
                left.append(arg)
            elif action == "event":
                return action, arg, pause
                
        if newstate:
            return "continue", newstate, min(pauses)
        else:
            return "next", min(left), None

    def visit(self):
        return [ j for i in self.blocks for j in i.visit() ]


# The choice statement.

class RawChoice(RawStatement):

    def __init__(self, loc, chance, block):
        self.loc = loc
        self.choices = [ (chance, block) ]

    def compile(self, ctx):
        compiling(self.loc)
        return Choice(self.loc, [ (ctx.eval(chance), block.compile(ctx)) for chance, block in self.choices])

    def predict(self, ctx, callback):
        for i, j in self.choices:
            j.predict(ctx, callback)

class Choice(Statement):

    def __init__(self, loc, choices):
        self.loc = loc
        self.choices = choices

    def execute(self, trans, st, state, event):

        executing(self.loc)
        
        if state is None:

            total = 0
            for chance, choice in self.choices:
                total += chance

            n = random.uniform(0, total)

            for chance, choice in self.choices:
                if n < chance:
                    break
                n -= chance

            cstate = None

        else:
            choice, cstate = state

        action, arg, pause = choice.execute(trans, st, cstate, event)

        if action == "continue":
            return "continue", (choice, arg), pause
        else:
            return action, arg, None

    def visit(self):
        return [ j for i in self.choices for j in i[1].visit() ]

        
# The Time statement.

class RawTime(RawStatement):

    def __init__(self, loc, time):
        self.loc = loc
        self.time = time

    def compile(self, ctx):
        compiling(self.loc)
        return Time(self.loc, ctx.eval(self.time))

class Time(Statement):

    def __init__(self, loc, time):
        self.loc = loc
        self.time = time

    def execute(self, trans, st, state, event):
        return "continue", None, None
        

# The On statement.

class RawOn(RawStatement):

    def __init__(self, loc, name, block):
        self.handlers = { name : block }

    def compile(self, ctx):

        compiling(self.loc)

        handlers = { }

        for k, v in self.handlers.iteritems():
            handlers[k] = v.compile(ctx)

        return On(self.loc, handlers)

    def predict(self, ctx, callback):
        for i in self.handlers.itervalues():
            i.predict(ctx, callback)

class On(Statement):

    def __init__(self, loc, handlers):
        self.loc = loc
        self.handlers = handlers
    
    def execute(self, trans, st, state, event):

        executing(self.loc)
        
        # If it's our first time through, start in the start state.
        if state is None:
            state = ("start", st, None)

        # If we have an external event, and we have a handler for it,
        # handle it.
        if event in self.handlers:
            state = (event, st, None)

        name, start, cstate = state

        while True:

            # If we don't have a handler, return until we change event.
            if name not in self.handlers:
                return "continue", (name, start, cstate), None
            
            action, arg, pause = self.handlers[name].execute(trans, st - start, cstate, event)

            # If we get a continue, save our state.
            if action == "continue":
                return "continue", (name, start, arg), pause

            # If we get a next, then try going to the default
            # event, unless we're already in default, in which case we
            # go to None.
            elif action == "next":
                if name == "default":
                    name = None
                else:
                    name = "default"

                start = st - arg
                cstate = None

                continue

            # If we get an event, then either handle it if we can, or
            # pass it up the stack if we can't.
            elif action == "event":

                name, arg = arg

                if name in self.handlers:
                    start = st - arg
                    cstate = None
                    continue

                return "event", (name, arg), None

    def visit(self):
        return [ j for i in self.handlers.itervalues() for j in i.visit() ]


# Event statement.
            
class RawEvent(RawStatement):

    def __init__(self, loc, name):
        self.loc = loc
        self.name = name

    def compile(self, ctx):
        return Event(self.loc, self.name)

    
class Event(Statement):

    def __init__(self, loc, name):
        self.loc = loc
        self.name = name

    def execute(self, trans, st, state, event):
        return "event", (self.name, st), None
    
    
# This parses an ATL block.
def parse_atl(l):

    l.advance()
    block_loc = l.get_location()

    statements = [ ]

    while not l.eob:

        loc = l.get_location()
        
        if l.keyword('repeat'):

            repeats = l.simple_expression()
            statements.append(RawRepeat(loc, repeats))

        elif l.keyword('block'):
            l.require(':')
            l.expect_eol()
            l.expect_block('block')

            block = parse_atl(l.subblock_lexer())            
            statements.append(block)

        elif l.keyword('parallel'):
            l.require(':')
            l.expect_eol()
            l.expect_block('parallel')
            
            block = parse_atl(l.subblock_lexer())
            statements.append(RawParallel(loc, block))

        elif l.keyword('choice'):

            chance = l.simple_expression()
            if not chance:
                chance = "1.0"

            l.require(':')
            l.expect_eol()
            l.expect_block('choice')
            
            block = parse_atl(l.subblock_lexer())
            statements.append(RawChoice(loc, chance, block))

        elif l.keyword('on'):

            name = l.require(l.name)

            l.require(':')
            l.expect_eol()
            l.expect_block('on')
            
            block = parse_atl(l.subblock_lexer())
            statements.append(RawOn(loc, name, block))

        elif l.keyword('time'):
            time = l.require(l.simple_expression)
            l.expect_noblock('time')

            statements.append(RawTime(loc, time))

        elif l.keyword('event'):
            name = l.require(l.name)
            l.expect_noblock('event')

            statements.append(RawEvent(loc, name))

        elif l.keyword('pass'):
            l.expect_noblock('pass')
            statements.append(None)
            
        else:

            # If we can't assign it it a statement more specifically,
            # we try to parse it into a RawMultipurpose. That will
            # then be turned into another statement, as appropriate.
            
            # The RawMultipurpose we add things to.
            rm = renpy.atl.RawMultipurpose(loc)

            # First, look for a warper.
            cp = l.checkpoint()
            warper = l.name()

            if warper in warpers:
                duration = l.require(l.simple_expression)
            else:
                l.revert(cp)

                warper = None
                duration = "0"
                
            rm.add_warper(warper, duration)

            # Now, look for properties and simple_expressions.
            while True:

                # Parse revolution keywords.
                if l.keyword('clockwise'):
                    rm.add_revolution('clockwise')
                    continue

                if l.keyword('counterclockwise'):
                    rm.add_revolution('counterclockwise')
                    continue

                if l.keyword('circles'):
                    expr = l.require(l.simple_expression)
                    rm.add_circles(expr)

                # Try to parse a property. 
                cp = l.checkpoint()
                
                prop = l.name()

                if prop in PROPERTIES:
                    expr = l.require(l.simple_expression)

                    # We either have a property or a spline. It's the
                    # presence of knots that determine which one it is.

                    knots = [ ]
                    
                    while l.keyword('knot'):
                        knots.append(l.require(l.simple_expression))

                    if knots:
                        knots.append(expr)
                        rm.add_spline(prop, knots)
                    else:
                        rm.add_property(prop, expr)

                    continue
                    
                # Otherwise, try to parse it as a simple expressoon,
                # with an optional with clause.

                l.revert(cp)

                expr = l.simple_expression()

                if not expr:
                    break

                if l.keyword("with"):
                    with_expr = l.require(l.simple_expression)
                else:
                    with_expr = None

                rm.add_expression(expr, with_expr)

            l.expect_noblock('ATL')
                
            statements.append(rm)
            
            
        if l.eol():
            l.advance()
            continue

        l.require(",", "comma or end of line")

        
    # Merge together statements that need to be merged together.

    merged = [ ]
    old = None

    for new in statements:

        if isinstance(old, RawParallel) and isinstance(new, RawParallel):
            old.blocks.extend(new.blocks)
            continue

        elif isinstance(old, RawChoice) and isinstance(new, RawChoice):
            old.choices.extend(new.choices)
            continue

        elif isinstance(old, RawOn) and isinstance(new, RawOn):
            old.handlers.update(new.handlers)
            continue

        # None is a pause statement, which gets skipped, but also
        # prevents things from combining.
        elif new is None:
            old = new
            continue
        
        merged.append(new)
        old = new

    return RawBlock(block_loc, merged)
