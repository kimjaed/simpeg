import Utils, numpy as np, scipy.sparse as sp


class BaseRx(object):
    """SimPEG Receiver Object"""

    locs = None   #: Locations (nRx x nDim)

    knownRxTypes = None  #: Set this to a list of strings to ensure that txType is known

    projGLoc = 'CC'  #: Projection grid location, default is CC

    storeProjections = True #: Store calls to getP (organized by mesh)

    def __init__(self, locs, rxType, **kwargs):
        self.locs = locs
        self.rxType = rxType
        self._Ps = {}
        Utils.setKwargs(self, **kwargs)

    @property
    def rxType(self):
        """Receiver Type"""
        return getattr(self, '_rxType', None)
    @rxType.setter
    def rxType(self, value):
        known = self.knownRxTypes
        if known is not None:
            assert value in known, "rxType must be in ['%s']" % ("', '".join(known))
        self._rxType = value

    @property
    def nD(self):
        """Number of data in the receiver."""
        return self.locs.shape[0]

    def getP(self, mesh):
        """
            Returns the projection matrices as a
            list for all components collected by
            the receivers.

            .. note::

                Projection matrices are stored as a dictionary listed by meshes.
        """
        if mesh in self._Ps:
            return self._Ps[mesh]

        P = mesh.getInterpolationMat(self.locs, self.projGLoc)
        if self.storeProjections:
            self._Ps[mesh] = P
        return P


class BaseTimeRx(BaseRx):
    """SimPEG Receiver Object"""

    times = None   #: Times when the receivers were active.
    projTLoc = 'N'

    def __init__(self, locs, times, rxType, **kwargs):
        self.times = times
        BaseRx.__init__(self, locs, rxType, **kwargs)

    @property
    def nD(self):
        """Number of data in the receiver."""
        return self.locs.shape[0] * len(self.times)

    def getSpatialP(self, mesh):
        """
            Returns the spatial projection matrix.

            .. note::

                This is not stored in memory, but is created on demand.
        """
        return mesh.getInterpolationMat(self.locs, self.projGLoc)

    def getTimeP(self, timeMesh):
        """
            Returns the time projection matrix.

            .. note::

                This is not stored in memory, but is created on demand.
        """
        return timeMesh.getInterpolationMat(self.times, self.projTLoc)

    def getP(self, mesh, timeMesh):
        """
            Returns the projection matrices as a
            list for all components collected by
            the receivers.

            .. note::

                Projection matrices are stored as a dictionary (mesh, timeMesh) if storeProjections is True
        """
        if (mesh, timeMesh) in self._Ps:
            return self._Ps[(mesh, timeMesh)]

        Ps = self.getSpatialP(mesh)
        Pt = self.getTimeP(timeMesh)
        P = sp.kron(Pt, Ps)

        if self.storeProjections:
            self._Ps[(mesh, timeMesh)] = P

        return P


class BaseTx(object):
    """SimPEG Transmitter Object"""

    loc    = None #: Location [x,y,z]

    rxList = None #: SimPEG Receiver List
    rxPair = BaseRx

    knownTxTypes = None #: Set this to a list of strings to ensure that txType is known

    def __init__(self, loc, txType, rxList, **kwargs):
        assert type(rxList) is list, 'rxList must be a list'
        for rx in rxList:
            assert isinstance(rx, self.rxPair), 'rxList must be a %s'%self.rxPair.__name__
        assert len(set(rxList)) == len(rxList), 'The rxList must be unique'

        self.loc    = loc
        self.txType = txType
        self.rxList = rxList
        Utils.setKwargs(self, **kwargs)

    @property
    def txType(self):
        """Transmitter Type"""
        return getattr(self, '_txType', None)
    @txType.setter
    def txType(self, value):
        known = self.knownTxTypes
        if known is not None:
            assert value in known, "txType must be in ['%s']" % ("', '".join(known))
        self._txType = value

    @property
    def nD(self):
        """Number of data"""
        return self.vnD.sum()

    @property
    def vnD(self):
        """Vector number of data"""
        return np.array([rx.nD for rx in self.rxList])


class Data(object):
    """Fancy data storage by Tx and Rx"""

    def __init__(self, survey, v=None):
        self.survey = survey
        self._dataDict = {}
        for tx in self.survey.txList:
            self._dataDict[tx] = {}
        if v is not None:
            self.fromvec(v)

    def _ensureCorrectKey(self, key):
        if type(key) is tuple:
            if len(key) is not 2:
                raise KeyError('Key must be [Tx, Rx]')
            if key[0] not in self.survey.txList:
                raise KeyError('Tx Key must be a transmitter in the survey.')
            if key[1] not in key[0].rxList:
                raise KeyError('Rx Key must be a receiver for the transmitter.')
            return key
        elif isinstance(key, self.survey.txPair):
            if key not in self.survey.txList:
                raise KeyError('Key must be a transmitter in the survey.')
            return key, None
        else:
            raise KeyError('Key must be [Tx] or [Tx,Rx]')

    def __setitem__(self, key, value):
        tx, rx = self._ensureCorrectKey(key)
        assert rx is not None, 'set data using [Tx, Rx]'
        assert type(value) == np.ndarray, 'value must by ndarray'
        assert value.size == rx.nD, "value must have the same number of data as the transmitter."
        self._dataDict[tx][rx] = Utils.mkvc(value)

    def __getitem__(self, key):
        tx, rx = self._ensureCorrectKey(key)
        if rx is not None:
            if rx not in self._dataDict[tx]:
                raise Exception('Data for receiver has not yet been set.')
            return self._dataDict[tx][rx]

        return np.concatenate([self[tx,rx] for rx in tx.rxList])

    def tovec(self):
        return np.concatenate([self[tx] for tx in self.survey.txList])

    def fromvec(self, v):
        v = Utils.mkvc(v)
        assert v.size == self.survey.nD, 'v must have the correct number of data.'
        indBot, indTop = 0, 0
        for tx in self.survey.txList:
            for rx in tx.rxList:
                indTop += rx.nD
                self[tx, rx] = v[indBot:indTop]
                indBot += rx.nD


class Fields(object):
    """Fancy Field Storage

        u[:,'phi'] = phi
        print u[tx0,'phi']

    """

    knownFields = None  #: the known fields, a dict with locations, e.g. {"phi": "CC", "b": "F"}
    txPair = BaseTx
    dtype = float  #: dtype is the type of the storage matrix. This can be a dictionary.

    def __init__(self, mesh, survey, **kwargs):
        self.survey = survey
        self.mesh = mesh
        Utils.setKwargs(self, **kwargs)
        self._fields = {}

    def _storageShape(self, nP):
        nTx = self.survey.nTx
        return (nP, nTx)

    def _initStore(self, name):
        if name in self._fields:
            return self._fields[name]

        assert name in self.knownFields, 'field name is not known.'

        loc = self.knownFields[name]

        nP = {'CC': self.mesh.nC,
              'N':  self.mesh.nN,
              'F':  self.mesh.nF,
              'E':  self.mesh.nE}[loc]

        if type(self.dtype) is dict:
            dtype = self.dtype[name]
        else:
            dtype = self.dtype
        field = np.zeros(self._storageShape(nP), dtype=dtype)

        self._fields[name] = field

        return field

    def _txIndex(self, txTestList):
        if type(txTestList) is slice:
            ind = txTestList
        else:
            if type(txTestList) is not list:
                txTestList = [txTestList]
            for txTest in txTestList:
                if not isinstance(txTest, self.txPair):
                    raise KeyError('First index must be a Transmitter')
                if txTest not in self.survey.txList:
                    raise KeyError('Invalid Transmitter, not in survey list.')

            ind = np.in1d(self.survey.txList, txTestList)
        return ind

    def _nameIndex(self, name):

        if type(name) is slice:
            assert name == slice(None,None,None), 'Fancy field name slicing is not supported... yet.'
            name = None

        if name is not None and name not in self.knownFields:
            raise KeyError('Invalid field name')
        return name

    def _indexAndNameFromKey(self, key):
        if type(key) is not tuple:
            key = (key,)
        if len(key) == 1:
            key += (None,)

        assert len(key) == 2, 'must be [Tx, fieldName]'

        txTestList, name = key
        name = self._nameIndex(name)
        ind = self._txIndex(txTestList)
        return ind, name

    def __setitem__(self, key, value):
        ind, name = self._indexAndNameFromKey(key)
        if name is None:
            freq = key
            assert type(value) is dict, 'New fields must be a dictionary, if field is not specified.'
            newFields = value
        elif name in self.knownFields:
            newFields = {name: value}
        else:
            raise Exception('Unknown setter')

        for name in newFields:
            field = self._initStore(name)
            self._setField(field, newFields[name], ind)

    def __getitem__(self, key):
        ind, name = self._indexAndNameFromKey(key)
        if name is None:
            out = {}
            for name in self._fields:
                out[name] = self._getField(name, ind)
            return out
        return self._getField(name, ind)

    def _setField(self, field, val, ind):
        if type(val) is np.ndarray and (field.shape[1] == 1 or val.ndim == 1):
            val = Utils.mkvc(val,2)
        field[:,ind] = val

    def _getField(self, name, ind):
        out = self._fields[name][:,ind]
        if out.shape[1] == 1:
            out = Utils.mkvc(out)
        return out

    def __contains__(self, other):
       return self._fields.__contains__(other)

class TimeFields(Fields):
    """Fancy Field Storage for time domain problems

        u[:,'phi', timeInd] = phi
        print u[tx0,'phi']

    """

    def _storageShape(self, nP):
        nTx = self.survey.nTx
        nT = self.survey.prob.nT
        return (nP, nTx, nT + 1)

    def _indexAndNameFromKey(self, key):
        if type(key) is not tuple:
            key = (key,)
        if len(key) == 1:
            key += (None,)
        if len(key) == 2:
            key += (slice(None,None,None),)

        assert len(key) == 3, 'must be [Tx, fieldName, times]'

        txTestList, name, timeInd = key

        name = self._nameIndex(name)
        txInd = self._txIndex(txTestList)

        return (txInd, timeInd), name

    def _setField(self, field, val, ind):
        txInd, timeInd = ind
        if type(val) is np.ndarray and (val.ndim == 1):
            val = Utils.mkvc(val,2)
        field[:,txInd,timeInd] = val

    def _getField(self, name, ind):
        txInd, timeInd = ind
        out = self._fields[name][:,txInd,timeInd]
        if out.shape[1] == 1:
            if out.ndim == 2:
                out = out[:,0]
            else:
                out = out[:,0,:]
        return out


class BaseSurvey(object):
    """Survey holds the observed data, and the standard deviations."""

    __metaclass__ = Utils.SimPEGMetaClass

    std = None       #: Estimated Standard Deviations
    dobs = None      #: Observed data
    dtrue = None     #: True data, if data is synthetic
    mtrue = None     #: True model, if data is synthetic

    counter = None   #: A SimPEG.Utils.Counter object

    def __init__(self, **kwargs):
        Utils.setKwargs(self, **kwargs)

    txPair = BaseTx  #: Transmitter Pair

    @property
    def txList(self):
        """Transmitter List"""
        return getattr(self, '_txList', None)

    @txList.setter
    def txList(self, value):
        assert type(value) is list, 'txList must be a list'
        assert np.all([isinstance(tx, self.txPair) for tx in value]), 'All transmitters must be instances of %s' % self.txPair.__name__
        assert len(set(value)) == len(value), 'The txList must be unique'
        self._txList = value

    @property
    def prob(self):
        """
        The geophysical problem that explains this survey, use::

            survey.pair(prob)
        """
        return getattr(self, '_prob', None)

    @property
    def mesh(self):
        """Mesh of the paired problem."""
        if self.ispaired:
            return self.prob.mesh
        raise Exception('Pair survey to a problem to access the problems mesh.')

    def pair(self, p):
        """Bind a problem to this survey instance using pointers"""
        assert hasattr(p, 'surveyPair'), "Problem must have an attribute 'surveyPair'."
        assert isinstance(self, p.surveyPair), "Problem requires survey object must be an instance of a %s class."%(p.surveyPair.__name__)
        if p.ispaired:
            raise Exception("The problem object is already paired to a survey. Use prob.unpair()")
        self._prob = p
        p._survey = self

    def unpair(self):
        """Unbind a problem from this survey instance"""
        if not self.ispaired: return
        self.prob._survey = None
        self._prob = None

    @property
    def ispaired(self): return self.prob is not None

    @property
    def nD(self):
        """Number of data"""
        return self.vnD.sum()

    @property
    def vnD(self):
        """Vector number of data"""
        return np.array([tx.nD for tx in self.txList])

    @property
    def nTx(self):
        """Number of Transmitters"""
        return len(self.txList)

    @Utils.count
    @Utils.requires('prob')
    def dpred(self, m, u=None):
        """dpred(m, u=None)

            Create the projected data from a model.
            The field, u, (if provided) will be used for the predicted data
            instead of recalculating the fields (which may be expensive!).

            .. math::

                d_\\text{pred} = P(u(m))

            Where P is a projection of the fields onto the data space.
        """
        if u is None: u = self.prob.fields(m)
        return Utils.mkvc(self.projectFields(u))


    @Utils.count
    def projectFields(self, u):
        """projectFields(u)

            This function projects the fields onto the data space.

            .. math::

                d_\\text{pred} = \mathbf{P} u(m)
        """
        raise NotImplemented('projectFields is not yet implemented.')

    @Utils.count
    def projectFieldsDeriv(self, u):
        """projectFieldsDeriv(u)

            This function s the derivative of projects the fields onto the data space.

            .. math::

                \\frac{\partial d_\\text{pred}}{\partial u} = \mathbf{P}
        """
        raise NotImplemented('projectFields is not yet implemented.')

    @Utils.count
    def residual(self, m, u=None):
        """residual(m, u=None)

            :param numpy.array m: geophysical model
            :param numpy.array u: fields
            :rtype: numpy.array
            :return: data residual

            The data residual:

            .. math::

                \mu_\\text{data} = \mathbf{d}_\\text{pred} - \mathbf{d}_\\text{obs}

        """
        return Utils.mkvc(self.dpred(m, u=u) - self.dobs)


    @property
    def Wd(self):
        """
            Data weighting matrix. This is a covariance matrix used in::

                def residualWeighted(m,u=None):
                    return self.Wd*self.residual(m, u=u)

            By default, this is based on the norm of the data plus a noise floor.

        """
        if getattr(self,'_Wd',None) is None:
            print 'SimPEG is making Survey.Wd to be norm of the data plus a floor.'
            eps = np.linalg.norm(Utils.mkvc(self.dobs),2)*1e-5
            self._Wd = 1/(abs(self.dobs)*self.std+eps)
        return self._Wd
    @Wd.setter
    def Wd(self, value):
        self._Wd = value

    def residualWeighted(self, m, u=None):
        """residualWeighted(m, u=None)

            :param numpy.array m: geophysical model
            :param numpy.array u: fields
            :rtype: numpy.array
            :return: weighted data residual

            The weighted data residual:

            .. math::

                \mu_\\text{data}^{\\text{weighted}} = \mathbf{W}_d(\mathbf{d}_\\text{pred} - \mathbf{d}_\\text{obs})

            Where \\\\(W_d\\\\) is a covariance matrix that weights the data residual.
        """
        return Utils.mkvc(self.Wd*self.residual(m, u=u))

    @property
    def isSynthetic(self):
        "Check if the data is synthetic."
        return self.mtrue is not None


    #TODO: Move this to the survey class?
    # @property
    # def phi_d_target(self):
    #     """
    #     target for phi_d

    #     By default this is the number of data.

    #     Note that we do not set the target if it is None, but we return the default value.
    #     """
    #     if getattr(self, '_phi_d_target', None) is None:
    #         return self.data.dobs.size #
    #     return self._phi_d_target

    # @phi_d_target.setter
    # def phi_d_target(self, value):
    #     self._phi_d_target = value
