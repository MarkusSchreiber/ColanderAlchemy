# schema.py
# Copyright (C) 2012 the ColanderAlchemy authors and contributors
# <see AUTHORS file>
#
# This module is part of ColanderAlchemy and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

import logging

import colander
from colander import (Mapping,
                      drop,
                      required,
                      SchemaNode,
                      Sequence)
from sqlalchemy import (Boolean,
                        Date,
                        DateTime,
                        Enum,
                        Float,
                        inspect,
                        Integer,
                        String,
                        Numeric,
                        Time)
from sqlalchemy.schema import (FetchedValue, ColumnDefault)
from sqlalchemy.orm import (ColumnProperty, RelationshipProperty)


__all__ = ['SQLAlchemySchemaNode']

log = logging.getLogger(__name__)


def _creation_order(obj):
    """
    Used for sorting SQLAlchemy attributes in the order that
    they were defined
    """
    if isinstance(obj, ColumnProperty):
        return obj.columns[0]._creation_order
    else:
        return obj._creation_order


class SQLAlchemySchemaNode(colander.SchemaNode):
    """ Build a Colander Schema based on the SQLAlchemy mapped class.
    """

    sqla_info_key = 'colanderalchemy'
    ca_class_key = '__colanderalchemy_config__'

    def __init__(self, class_, includes=None,
                 excludes=None, overrides=None, unknown='ignore', **kw):
        """ Initialise the given mapped schema according to options provided.

        Arguments/Keywords

        class\_
           An ``SQLAlchemy`` mapped class that you want a ``Colander`` schema
           to be generated for.

           To declaratively customise ``Colander`` ``SchemaNode`` options,
           add a ``__colanderalchemy_config__`` attribute to your initial
           class declaration like so::

               class MyModel(Base):
                   __colanderalchemy_config__ = {'title': 'Custom title',
                                                 'description': 'Sample'}
                   ...
        includes
           Iterable of attributes to include from the resulting schema. Using
           this option will ensure *only* the explicitly mentioned attributes
           are included and *all others* are excluded.

           Incompatible with :attr:`excludes`. Default: None.
        excludes
           Iterable of attributes to exclude from the resulting schema. Using
           this option will ensure *only* the explicitly mentioned attributes
           are excluded and *all others* are included.

           Incompatible with :attr:`includes`. Default: None.
        overrides
            A dict-like structure that consists of schema attributes to
            override imperatively. Values provides as part of :attr:`overrides`
            will take precendence over all others.
        unknown
           Represents the `unknown` argument passed to
           :class:`colander.Mapping`.

           From Colander:

           ``unknown`` controls the behavior of this type when an unknown
           key is encountered in the cstruct passed to the deserialize
           method of this instance.

           Default: 'ignore'
        \*\*kw
           Represents *all* other options able to be passed to a
           :class:`colander.SchemaNode`. Keywords passed will influence the
           resulting mapped schema accordingly (for instance, passing
           ``title='My Model'`` means the returned schema will have its
           ``title`` attribute set accordingly.

           See
           http://docs.pylonsproject.org/projects/colander/en/latest/basics.html
           for more information.
        """

        self.inspector = inspect(class_)
        kwargs = kw.copy()

        # Obtain configuration specific from the mapped class
        kwargs.update(getattr(self.inspector.class_, self.ca_class_key, {}))

        # The default type of this SchemaNode is Mapping.
        colander.SchemaNode.__init__(self, Mapping(unknown), **kwargs)
        self.class_ = class_
        self.includes = includes or {}
        self.excludes = excludes or {}
        self.overrides = overrides or {}
        self.unknown = unknown
        self.declarative_overrides = {}
        self.kwargs = kwargs or {}
        self.add_nodes(self.includes, self.excludes, self.overrides)

    def add_nodes(self, includes, excludes, overrides):

        # sorted to maintain the order in which the attributes
        # are defined
        for prop in sorted(self.inspector.attrs, key=_creation_order):

            name = prop.key

            if name in excludes and name in includes:
                msg = 'excludes and includes are mutually exclusive.'
                raise ValueError(msg)

            if name in excludes or (includes and name not in includes):
                log.debug('Attribute %s skipped imperatively', name)
                continue

            name_overrides_copy = overrides.get(name, {}).copy()

            if isinstance(prop, ColumnProperty):
                node = self.get_schema_from_column(
                    prop,
                    name_overrides_copy
                )
            elif isinstance(prop, RelationshipProperty):
                node = self.get_schema_from_relationship(
                    prop,
                    name_overrides_copy
                )
            else:
                log.debug(
                    'Attribute %s skipped due to not being '
                    'a ColumnProperty or RelationshipProperty',
                    name
                )
                continue

            if node is not None:
                self.add(node)

    def get_schema_from_column(self, prop, overrides):
        """ Build and return a :class:`colander.SchemaNode` for a given Column.

        This method uses information stored in the column within the ``info``
        that was passed to the Column on creation.  This means that
        ``Colander`` options can be specified declaratively in
        ``SQLAlchemy`` models using the ``info`` argument that you can
        pass to :class:`sqlalchemy.Column`.

        Arguments/Keywords

        prop
            A given :class:`sqlalchemy.orm.properties.ColumnProperty`
            instance that represents the column being mapped.
        overrides
            A dict-like structure that consists of schema attributes to
            override imperatively. Values provides as part of :attr:`overrides`
            will take precendence over all others.
        """

        # The name of the SchemaNode is the ColumnProperty key.
        name = prop.key
        kwargs = dict(name=name)
        column = prop.columns[0]
        declarative_overrides = column.info.get(self.sqla_info_key, {}).copy()
        self.declarative_overrides[name] = declarative_overrides.copy()

        key = 'exclude'

        if key not in overrides and declarative_overrides.pop(key, False):
            log.debug('Column %s skipped due to declarative overrides', name)
            return None

        if overrides.pop(key, False):
            log.debug('Column %s skipped due to imperative overrides', name)
            return None

        self.check_overrides(name, 'name', declarative_overrides, overrides)

        # The SchemaNode built using the ColumnProperty has no children.
        children = []

        # The type of the SchemaNode will be evaluated using the Column type.
        # User can overridden the default type via Column.info or
        # imperatively using overrides arg in SQLAlchemySchemaNode.__init__

        # Support sqlalchemy.types.TypeDecorator
        column_type = getattr(column.type, 'impl', column.type)

        imperative_type = overrides.pop('typ', None)
        declarative_type = declarative_overrides.pop('typ', None)

        if imperative_type is not None:
            if hasattr(imperative_type, '__call__'):
                type_ = imperative_type()
            else:
                type_ = imperative_type
            log.debug('Column %s: type overridden imperatively: %s.',
                      name, type_)

        elif declarative_type is not None:
            if hasattr(declarative_type, '__call__'):
                type_ = declarative_type()
            else:
                type_ = declarative_type
            log.debug('Column %s: type overridden via declarative: %s.',
                      name, type_)

        elif isinstance(column_type, Boolean):
            type_ = colander.Boolean()

        elif isinstance(column_type, Date):
            type_ = colander.Date()

        elif isinstance(column_type, DateTime):
            type_ = colander.DateTime(default_tzinfo=None)

        elif isinstance(column_type, Enum):
            type_ = colander.String()
            kwargs["validator"] = colander.OneOf(column.type.enums)

        elif isinstance(column_type, Float):
            type_ = colander.Float()

        elif isinstance(column_type, Integer):
            type_ = colander.Integer()

        elif isinstance(column_type, String):
            type_ = colander.String()
            kwargs["validator"] = colander.Length(0, column.type.length)

        elif isinstance(column_type, Numeric):
            type_ = colander.Decimal()

        elif isinstance(column_type, Time):
            type_ = colander.Time()

        else:
            raise NotImplementedError('Unknown type: %s' % column_type)

        """
        Add default values

        possible values for default in SQLA:
         1. plain non-callable Python value
              - give to Colander as a default
         2. SQL expression (derived from ColumnElement)
              - leave default blank and allow SQLA to fill
         3. Python callable with 0 or 1 args
            1 arg version takes ExecutionContext
              - leave default blank and allow SQLA to fill

        all values for server_default should be ignored for
        Colander default
        """
        if (isinstance(column.default, ColumnDefault)
                and column.default.is_scalar):
            kwargs["default"] = column.default.arg

        """
        Add missing values

        possible values for default in SQLA:
         1. plain non-callable Python value
              - give to Colander as a missing unless nullable
         2. SQL expression (derived from ColumnElement)
              - set missing to 'drop' to allow SQLA to fill this in
                and make it an unrequired field
         3. Python callable with 0 or 1 args
            1 arg version takes ExecutionContext
              - set missing to 'drop' to allow SQLA to fill this in
                and make it an unrequired field

        if nullable, then allowing missing = drop

        all values for server_default should result in 'drop'
        for Colander missing

        autoincrement results in drop
        """
        if isinstance(column.default, ColumnDefault):
            if column.default.is_callable:
                kwargs["missing"] = drop
            elif column.default.is_clause_element:  # SQL expression
                kwargs["missing"] = drop
            elif column.default.is_scalar:
                kwargs["missing"] = column.default.arg
        elif column.nullable:
            kwargs["missing"] = drop
        elif isinstance(column.server_default, FetchedValue):
            kwargs["missing"] = drop  # value generated by SQLA backend
        elif (hasattr(column.table, "_autoincrement_column")
              and id(column.table._autoincrement_column) == id(column)):
            # this column is the autoincrement column, so we can drop
            # it if it's missing and let the database generate it
            kwargs["missing"] = drop

        kwargs.update(declarative_overrides)
        kwargs.update(overrides)

        return colander.SchemaNode(type_, *children, **kwargs)

    def check_overrides(self, name, arg, declarative_overrides, overrides):
        msg = None
        if arg in declarative_overrides:
            msg = '%s: argument %s cannot be overridden via info kwarg.'

        elif arg in overrides:
            msg = '%s: argument %s cannot be overridden imperatively.'

        if msg:
            raise ValueError(msg % (name, arg))

    def get_schema_from_relationship(self, prop, overrides):
        """ Build and return a :class:`colander.SchemaNode` for a relationship.

        The mapping process will translate one-to-many and many-to-many
        relationships from SQLAlchemy into a ``Sequence`` of ``Mapping`` nodes
        in Colander, and translate one-to-one and many-to-one relationships
        into a ``Mapping`` node in Colander.  The related class involved in the
        relationship will be recursively mapped by ColanderAlchemy as part of
        this process, following the same mapping process.

        This method uses information stored in the relationship within
        the ``info`` that was passed to the relationship on creation.
        This means that ``Colander`` options can be specified
        declaratively in ``SQLAlchemy`` models using the ``info``
        argument that you can pass to
        :meth:`sqlalchemy.orm.relationship`.

        For all relationships, the settings will only be applied to the outer
        Sequence or Mapping. To customise the inner schema node, create the
        attribute ``__colanderalchemy_config__`` on the related model with a
        dict-like structure corresponding to the Colander options that should
        be customised.

        Arguments/Keywords

        prop
            A given :class:`sqlalchemy.orm.properties.RelationshipProperty`
            instance that represents the relationship being mapped.
        overrides
            A dict-like structure that consists of schema attributes to
            override imperatively. Values provides as part of :attr:`overrides`
            will take precendence over all others.  Example keys include
            ``children``, ``includes``, ``excludes``, ``overrides``.
        """

        # The name of the SchemaNode is the ColumnProperty key.
        name = prop.key
        kwargs = dict(name=name)
        declarative_overrides = prop.info.get(self.sqla_info_key, {}).copy()
        self.declarative_overrides[name] = declarative_overrides.copy()

        class_ = prop.mapper

        if declarative_overrides.pop('exclude', False):
            log.debug('Relationship %s skipped due to declarative overrides',
                      name)
            return None

        for key in ['name', 'typ']:
            self.check_overrides(name, key, declarative_overrides, overrides)

        key = 'children'
        imperative_children = overrides.pop(key, None)
        declarative_children = declarative_overrides.pop(key, None)
        if imperative_children is not None:
            children = imperative_children
            msg = 'Relationship %s: %s overridden imperatively.'
            log.debug(msg, name, key)

        elif declarative_children is not None:
            children = declarative_children
            msg = 'Relationship %s: %s overridden via declarative.'
            log.debug(msg, name, key)

        else:
            children = None

        key = 'includes'
        imperative_includes = overrides.pop(key, None)
        declarative_includes = declarative_overrides.pop(key, None)
        if imperative_includes is not None:
            includes = imperative_includes
            msg = 'Relationship %s: %s overridden imperatively.'
            log.debug(msg, name, key)

        elif declarative_includes is not None:
            includes = declarative_includes
            msg = 'Relationship %s: %s overridden via declarative.'
            log.debug(msg, name, key)

        else:
            includes = None

        key = 'excludes'
        imperative_excludes = overrides.pop(key, None)
        declarative_excludes = declarative_overrides.pop(key, None)

        if imperative_excludes is not None:
            excludes = imperative_excludes
            msg = 'Relationship %s: %s overridden imperatively.'
            log.debug(msg, name, key)

        elif declarative_excludes is not None:
            excludes = declarative_excludes
            msg = 'Relationship %s: %s overridden via declarative.'
            log.debug(msg, name, key)

        else:
            excludes = None

        # see issue #25 in ColanderAlchemy for possible patch
        if includes is None and excludes is None:
            includes = [p.key for p in inspect(class_).column_attrs]

        key = 'overrides'
        imperative_rel_overrides = overrides.pop(key, None)
        declarative_rel_overrides = declarative_overrides.pop(key, None)

        if imperative_rel_overrides is not None:
            rel_overrides = imperative_rel_overrides
            msg = 'Relationship %s: %s overridden imperatively.'
            log.debug(msg, name, key)

        elif declarative_rel_overrides is not None:
            rel_overrides = declarative_rel_overrides
            msg = 'Relationship %s: %s overridden via declarative.'
            log.debug(msg, name, key)

        else:
            rel_overrides = None

        # Add default values for missing parameters.
        if prop.innerjoin:
            # Inner joined relationships imply it is mandatory
            missing = required
        else:
            # Any other join is thus optional
            missing = drop
        kwargs['missing'] = missing

        kwargs.update(declarative_overrides)
        kwargs.update(overrides)

        if children is not None:
            if prop.uselist:
                # xToMany relationships.
                return SchemaNode(Sequence(), *children, **kwargs)
            else:
                # xToOne relationships.
                return SchemaNode(Mapping(), *children, **kwargs)

        node = SQLAlchemySchemaNode(class_,
                                    name=name,
                                    includes=includes,
                                    excludes=excludes,
                                    overrides=rel_overrides,
                                    missing=missing)

        if prop.uselist:
            node = SchemaNode(Sequence(), node, **kwargs)

        node.name = name

        return node

    def dictify(self, obj):
        """ Return a dictified version of `obj` using schema information.

        The schema will be used to choose what attributes will be
        included in the returned dict.

        Thus, the return value of this function is suitable for consumption
        as a ``Deform`` ``appstruct`` and can be used to pre-populate
        forms in this specific use case.

        Arguments/Keywords

        obj
            An object instance to be converted to a ``dict`` structure.
            This object should conform to the given schema.  For
            example, ``obj`` should be an instance of this schema's
            mapped class, an instance of a sub-class, or something that
            has the same attributes.
        """
        dict_ = {}
        for node in self:

            name = node.name
            try:
                getattr(self.inspector.column_attrs, name)
                value = getattr(obj, name)

            except AttributeError:
                try:
                    prop = getattr(self.inspector.relationships, name)
                    if prop.uselist:
                        value = [self[name].children[0].dictify(o)
                                 for o in getattr(obj, name)]
                    else:
                        o = getattr(obj, name)
                        value = None if o is None else self[name].dictify(o)
                except AttributeError:
                    # The given node isn't part of the SQLAlchemy model
                    msg = 'SQLAlchemySchemaNode.dictify: %s not found on %s'
                    log.debug(msg, name, self)
                    continue

            if value is not None:
                dict_[name] = value

        return dict_

    def objectify(self, dict_, context=None):
        """ Return an object representing ``dict_`` using schema information.

        The schema will be used to choose how the data in the structure
        will be restored into SQLAlchemy model objects.
        The incoming ``dict_`` structure corresponds with one that may be
        created from the :meth:`dictify` method on the same schema.
        Relationships and backrefs will be restored in accordance with their
        specific configurations.

        The return value of this function will be suitable for
        adding into an SQLAlchemy session to be committed to a database.

        Arguments/Keywords

        dict\_
            An dictionary or similar data structure to be converted to a
            an SQLAlchemy object.  This data structure should conform to
            the given schema.  For example, ``dict_`` should be an
            appstruct (such as that returned from a Deform form
            submission), result of a call to this schema's
            :meth:`dictify` method, or a matching structure with
            relevant keys and nesting, if applicable.
        context
            Optional keyword argument that, if supplied, becomes the base
            object, with attributes and objects being applied to it.

            Specify a ``context`` in the situation where you already have
            an object that exists already, such as when you have a pre-existing
            instance of an SQLAlchemy model. If your model is already bound to
            a session, then this facilitates directly updating the database --
            just pass in your dict or appstruct, and your existing SQLAlchemy
            instance as ``context`` and this method will update all of its
            attributes.

            This is a perfect fit for something like a CRUD environment.

            Default: ``None``.  Defaults to instantiating a new instance of the
            mapped class associated with this schema.
        """
        mapper = self.inspector
        context = mapper.class_() if context is None else context
        for attr in dict_:
            if mapper.has_property(attr):
                prop = mapper.get_property(attr)
                value = dict_[attr]
                # Convert value into objects if property has a mapper
                if hasattr(prop, 'mapper'):
                    cls = prop.mapper.class_
                    if prop.uselist:
                        # Sequence of objects
                        value = [self[attr].children[0].objectify(obj)
                                 for obj in value]
                    else:
                        # Single object
                        value = self[attr].objectify(value)
                setattr(context, attr, value)
            else:
                # Ignore attributes if they are not mapped
                log.debug(
                    'SQLAlchemySchemaNode.objectify: %s not found on '
                    '%s. This property has been ignored.',
                    attr, self
                )
                continue

        return context

    def clone(self):
        cloned = self.__class__(self.class_,
                                self.includes,
                                self.excludes,
                                self.overrides,
                                self.unknown,
                                **self.kwargs)
        cloned.__dict__.update(self.__dict__)
        cloned.children = [node.clone() for node in self.children]
        return cloned
