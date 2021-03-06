#!/usr/bin/env python
# -*- coding: utf-8; fill-column: 100; truncate-lines: t -*-
#
# This file is part of JK Python extensions
# Copyright (C) 2008,2009,2012,2014 Jochen Küpper <jochen.kuepper@cfel.de>
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# If you use this programm for scientific work, you must correctly reference it; see LICENSE file for details.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not, see
# <http://www.gnu.org/licenses/>.

__author__ = "Jochen Küpper <jochen.kuepper@cfel.de>"

import numpy as np
import numpy.linalg
import tables

import cmistark.starkeffect
import cmistark.storage


Masses = {'H': 1.0078250321, 'D': 2.01410178, '2H': 2.01410178,
          'C': 12, 'N': 14.0030740052, 'O': 15.9949146221,
          'S': 31.97207070,
          'F': 18.9984032,
          'Cl': 35., 'CL35': 35., 'CL37': 37.,
          'BR': 78.9183371, 'BR79': 78.9183371, 'BR81': 80.9162906,
          'I': 126.90447}
Ordernumbers = {'H': 1, 'D': 1, 'C': 6, 'N': 7, 'O': 8, 'F': 9, 'S': 16, 'BR': 35, 'I': 53}


class _isomer_mass(tables.IsDescription):
    """Isomer mass represenation for pytables."""
    name  = tables.StringCol(64)
    num   = tables.UInt16Col()
    mass  = tables.Float64Col()



class State:
    """State label of molecule

    Currently only asymmetric top notation, but linear tops naturally fit and symmetric tops are placed in as described
    below.

    Public data:
    - max  Upper bound of any individual quantum number - actually any |qn| must be strictly smaller than max

    For symmetric tops only one K quantum number exists, which is placed in (the natural choice of) Ka or Kc depending
    on the case.
    """

    def __init__(self, J=0, Ka=0, Kc=0, M=0, isomer=0):
        self.max = 1000
        self.__initialize(J, Ka, Kc, M, isomer)
        self.__symtop_sign = 1

    def __initialize(self, J=0, Ka=0, Kc=0, M=0, isomer=0):
        """Store all info and creat a unique ID for the state.

        For symmetric tops, :math:`K` is stored in the natural choice of :math:`K_a` or :math:`K_c`. The state depends
        on the sign of the product of :math:`K\cdot{}M`, which is stored in the decimal place 15 (0-14 being used to
        encode J, Ka, Kc, M, isomer).

        """
        assert ((0 <= J < self.max) and (abs(Ka) < self.max) and (abs(Kc) < self.max) and (0 <= M < self.max)
                and (0 <= isomer < self.max))
        self.__labels = np.array([J, Ka, Kc, M, isomer], dtype=np.int64)
        self.__id = np.uint64(0)
        for i in range(self.__labels.size):
            self.__id += np.uint64(abs(self.__labels[i]) * self.max**i)
        # handle negative sign of symmetric-top K*M
        if Ka < 0 or Kc < 0:
            self.__symtop_sign = -1
            self.__id += np.uint64(1e15)

    def J(self):
        return self.__labels[0]

    def Ka(self):
        return self.__labels[1]

    def Kc(self):
        return self.__labels[2]

    def M(self):
        return self.__labels[3]

    def isomer(self):
        return self.__labels[4]

    def nssw(self, forbidden):
        """Give back nuclear spin weight 0 for nuclear-spin-statistically forbidden rve-states, 1 otherwise"""
        if "Ka" == forbidden and self.Ka() % 2 == 1: return 0
        if "Kb" == forbidden and (self.Ka() + self.Kc()) % 2 == 1: return 0
        if "Kc" == forbidden and self.Kc() % 2 == 1: return 0
        return 1

    def symtop_sign():
        return self.__symtop_sign

    def fromid(self, id):
        """Set quantum-numbers form id"""
        id = np.int64(id)
        self.__id = id
        self.__labels = np.zeros((5,), dtype=np.int64)
        for i in range(5):
            self.__labels[i] = id % self.max
            id //= self.max
        # handle negative sign of symmetric-top K*M
        self.__symtop_sign = id % 10
        id //= 10
        if self.__symtop_sign > 0:
            for i in [1,2]:
                self.__labels[i] = -self.__labels[i]
        return self

    def fromhdfname(self, hdfname):
        """Set quantum-numbers form hdf name.

        See hdfname() below for a description of the format.

        .. todo:: Implement symtop-sign usage
        """
        name = hdfname.replace("n","-")
        qn = np.array(name.split("/"))
        J, Ka, Kc, M, iso = qn.tolist()
        self.__initialize(np.int64(J[1:]), np.int64(Ka[1:]), np.int64(Kc[1:]), np.int64(M[1:]), np.int64(iso[1:]))
        return self

    def id(self):
        return self.__id

    def name(self):
        return "%d %d %d %d %d" % self.totuple()

    def hdfname(self):
        """Create HDF5 storage file name of state.

        Prepend '_' to all numbers to make them valid Python identifiers. We split the individual quantum numbers by '/'
        in order to provide subgrouping for faster transversal of the HDF5 directory.

        """
        name = "_%d/_%d/_%d/_%d/_%d" % self.totuple()
        name.replace("-","n")
        return name.replace("-","n")

    def toarray(self):
        return self.__labels

    def tolist(self):
        return self.__labels.tolist()

    def totuple(self):
        return tuple(self.__labels.tolist())




class Molecule(object):
    """Representation of a Molecule"""

    def __init__(self, storage=None, name="Generic molecule", readonly=False):
        """Create Molecule """
        try:
            if readonly:
                self.__storage = tables.open_file(storage, mode='r')
            else:
                self.__storage = tables.open_file(storage, mode='a', title=name)
                self.__storage.get_node("/")._v_title = name
        except:
            raise EnvironmentError("Cannot create nor open storage file")
            self.__storage = None


    def mueff(self, state):
        """Effective dipole moment :math:`\mu_{\\text{eff}}` as a function of the electric field strength.

        :return: effective dipole moment curve for the specified quantum ``state``.

        :rtype: pair (fields, :math:`\mu_{\\text{eff}}`), where the members of the pair are
            one-dimensional NumPy ndarrays.

        .. note:: The last datapoint for :math:`\mu_{\\text{eff}}`, at maximum field strenghs, is a
            forward difference of two Stark energy values, whereas all other datapoints for
            :math:`\mu_{\\text{eff}}` are central differences.

        """
        fields, energies = self.starkeffect(state)
        assert len(fields) == len(energies)
        mueff = np.zeros((len(fields),), np.float64)
        mueff[0]    = 0.
        mueff[1:-1] = (energies[0:-2] - energies[2:]) / (fields[2:] - fields[0:-2])
        mueff[-1]   = (energies[-2] - energies[-1]) / (fields[-1] - fields[-2])
        return fields, mueff


    def starkeffect(self, state, fields=None, energies=None):
        """Get or set the potential energies as a function of the electric field strength.

        :param state: Eigenstate for which the Stark effect is calculated.
        :param fields: Field strengths at which the eigenenergies are calculated (default: None).
        :param energy: Corresponding eigensergies at the given field strengths (default: None).

        When ``energies`` and ``fields`` are None, return the Stark curve for the specified quantum state. When
        ``energies`` and ``fields`` are specified, save the Stark curve for the specified quantum state in the
        Molecule's HDF5 storage file.

        """
        if energies is None and fields is None:
            return cmistark.storage.readVLArray(self.__storage, "/" + state.hdfname() + "/dcfield"), \
                cmistark.storage.readVLArray(self.__storage, "/" + state.hdfname() + "/dcstarkenergy"),
        elif energies is None or fields is None:
            raise SyntaxError
        else:
            assert len(fields) == len(energies)
            cmistark.storage.writeVLArray(self.__storage, "/" + state.hdfname(), "dcfield", fields)
            cmistark.storage.writeVLArray(self.__storage, "/" + state.hdfname(), "dcstarkenergy", energies)


    def starkeffect_calculation(self, param):
        """Perform an Stark effect calculation, get all available energies from the given Starkeffect
        object, and store them in our storage file.

        ..todo:: Improve diagnostics regarding the "create_table" try-except and distinguish
            "pre-existance" from real errors (and act accordingly)

        """
        try:
            self.__storage.create_table("/", 'masses', _isomer_mass, "Isomer masses")
        except:
            # Cannot create HDF5 table, continuing -- this is morst likely due to the fact that the
            # entry/file exists already
            pass
        if 'L' == param.type:
            Rotor = cmistark.starkeffect.LinearRotor
        elif 'S' == param.type:
            Rotor = cmistark.starkeffect.SymmetricRotor
        elif 'A' == param.type:
            Rotor = cmistark.starkeffect.AsymmetricRotor
        else:
            raise NotImplementedError("unknown rotor type in Stark energy calculation.")
        # calculate and store energies
        masses = self.__storage.root.masses
        new_isomer = True
        for isomer in masses.iterrows():
            if isomer['num'] == param.isomer:
                isomer['mass'] = param.mass
                new_isomer = False
        if new_isomer:
            isomer = self.__storage.root.masses.row
            isomer['name'] = param.name
            isomer['mass'] = param.mass
            isomer['num']  = param.isomer
            isomer.append()
        for M in param.M:
            energies = {}
            for field in param.dcfields:
                calc = Rotor(param, M, field)
                for state in calc.states():
                    id = state.id()
                    if id in energies:
                        energies[id].append(calc.energy(state))
                    else:
                        energies[id] = [calc.energy(state),]
            # store calculated values for this M
            for id in list(energies.keys()):
                self.starkeffect_merge(State().fromid(id), param.dcfields, energies[id])
            # flush HDF5 file after every M
            self.__storage.flush()


    def starkeffect_merge(self, state, newfields=None, newenergies=None):
        """Merge the specified pairs of field strength and Stark energies into the existing data.

        not really tested
        """
        assert len(newfields) == len(newenergies)
        try:
            oldfields, oldenergies = self.starkeffect(state)
            fields, energies = cmistark.storage.column_merge([oldfields, oldenergies], [newfields, newenergies])
        except tables.exceptions.NodeError:
            fields = newfields
            energies = newenergies
        self.starkeffect(state, fields, energies)


    def starkeffect_states(self):
        """Get a list of states for which we know the Stark effect."""
        list = []
        for groupJ in self.__storage.list_nodes(self.__storage.root, classname='Group'):
            for groupKa in self.__storage.list_nodes(groupJ, classname='Group'):
                for groupKc in self.__storage.list_nodes(groupKa, classname='Group'):
                    for groupM in self.__storage.list_nodes(groupKc, classname='Group'):
                        for groupIso in self.__storage.list_nodes(groupM, classname='Group'):
                            statename = (groupJ._v_name + '/' + groupKa._v_name + '/' + groupKc._v_name
                                         + '/' + groupM._v_name + '/' + groupIso._v_name)
                            if 'dcfield' == groupIso.dcfield.name and 'dcstarkenergy' == groupIso.dcstarkenergy.name:
                                list.append(State().fromhdfname(statename))
        return list


    def states_to_print(self, Jmin, Jmax, statelist=None):
        """Create a list of states to be printed/plotted according to the provided arguments

        Correctly creates list of states for the various rotor types

        .. todo:: Implement or remove
        """

        states = []
        return states



# some simple tests
if __name__ == "__main__":
    # test Stark calculation and storage/retrieval
    from cmistark.convert import *
    param = cmistark.starkeffect.CalculationParameter
    param.name = 'cis'
    param.isomer = 0
    param.watson = 'A'
    param.symmetry = 'C2a'
    param.rotcon = Hz2J(np.array([5000e5, 1500e5, 1200e5]))
    param.quartic = Hz2J(np.array([50., 1000., 500, 10., 600]))
    param.dipole = D2Cm(np.array([5, 0., 0.]))
    # calculation details
    param.M = [0]
    param.Jmin = 0
    param.Jmax_calc = 10
    param.Jmax_save =  5
    param.dcfields = kV_cm2V_m(np.linspace(0., 100., 101))
    # save and print
    mol = Molecule(storage="molecule.hdf")
    mol.starkeffect_calculation(param)
    for J in range (0, 3):
        Ka = 0
        for Kc in range(J, -1, -1):
            state = cmistark.molecule.State(J, Ka, Kc, 0, 0)
            fields, energies = mol.starkeffect(state)
            print(state.name(), V_m2kV_cm(fields), J2Hz(energies) / 1e6)
            if Kc > 0:
                Ka += 1
                state = cmistark.molecule.State(J, Ka, Kc, 0, 0)
                fields, energies = mol.starkeffect(state)
                print(state.name(), V_m2kV_cm(fields), J2Hz(energies) / 1e6)
