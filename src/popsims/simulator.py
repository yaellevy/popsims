##purpose: simulate a brown dwarf population
###
#imports
from .galaxy import * 
from .popsims import *
from .core_tools import *
from .relations import teff_to_spt_subdwarf
import seaborn as sns
#from tqdm import tqdm
#tqdm.pandas()


class Population(object):
    """
    Class for a poulation

    Attributes:
    ----
        x_grid: grid of values ( array)
        cdf:  corresponding values from the CDF
        nsample: optional, number of samples

    Properties:
    -------
        random draws

    Methods:
    --------

    Example:
    -------
        > x = np.arange(0, 10)
        > cdf = x**3/(x[-1]**3)
        > res= random_draw(x, cdf)

    """
    def __init__(self, **kwargs):

        self.imfpower= kwargs.get('imf_power', -0.6)
        self.binaryfraction= kwargs.get('binary_fraction', 0.2)
        self.binaryq= kwargs.get('binary_q', 4)
        self.evolmodel= kwargs.get('evolmodel', 'burrows1997')
        self.metallicity=kwargs.get('metallicity', 'dwarfs')
        self.agerange= kwargs.get('age_range', [0.01, 14.])
        self.massrange= kwargs.get('mass_range', [0.01, 1.])
        self.nsample= kwargs.get('nsample',1e4)
        self._distance=None

    def _sample_ages(self):
        return np.random.uniform(*self.agerange, int(self.nsample))

    def _sample_masses(self):
        #add specific IMFS
        if self.imfpower=='kroupa':
            m0=sample_from_powerlaw(-0.3, xmin=0.03, xmax= 0.08, nsample=int(self.nsample))
            m1=sample_from_powerlaw(-1.3, xmin=0.08, xmax= 0.5, nsample=int(self.nsample))
            m2=sample_from_powerlaw(-2.3, xmin=0.5, xmax= 100 , nsample=int(self.nsample))
            m= np.concatenate([m0, m1, m2]).flatten()
            mask= np.logical_and(m> self.massrange[0], m< self.massrange[1])
            masses= np.random.choice(m[mask], int(nsample))
            return masses

        else:
            return sample_from_powerlaw(self.imfpower, xmin=  self.massrange[0], xmax= self.massrange[1], nsample=int(self.nsample))

    def _interpolate_evolutionary_model(self, mass, age):
        return evolutionary_model_interpolator(mass, age, self.evolmodel)

    def simulate(self):
        """
        Class for a poulation

        Attributes:
        ----
            x_grid: grid of values ( array)
            cdf:  corresponding values from the CDF
            nsample: optional, number of samples

        Properties:
        -------
            random draws

        Methods:
        --------

        Example:
        -------
            > x = np.arange(0, 10)
            > cdf = x**3/(x[-1]**3)
            > res= random_draw(x, cdf)

        """
        #single stars
        m_singles=self._sample_masses()
        ages_singles= self._sample_ages()

        #binaries
        qs=sample_from_powerlaw(self.binaryq, xmin= 0., xmax=1., nsample=self.nsample)
        m_prims = self._sample_masses()
        m_sec=m_prims*qs
        ages_bin=self._sample_ages()

        #interpolate evolurionary models
        single_evol=self._interpolate_evolutionary_model(m_singles, ages_singles)
        primary_evol=self._interpolate_evolutionary_model(m_prims,ages_bin)
        secondary_evol=self._interpolate_evolutionary_model(m_sec,ages_bin)

        #temperatures
        teffs_singl =single_evol['temperature'].value
        teffs_primar=primary_evol['temperature'].value
        teffs_second=secondary_evol['temperature'].value

        #spectraltypes
        spts_singl=teff_to_spt_kirkpatrick(teffs_singl)
        spt_primar=teff_to_spt_kirkpatrick(teffs_primar)
        spt_second=teff_to_spt_kirkpatrick(teffs_second)

        #use pecaut for teff <2000 k
        spts_singl[teffs_singl >2000]= teff_to_spt_pecaut(teffs_singl[teffs_singl>2000])
        spt_primar[teffs_primar >2000]= teff_to_spt_pecaut(teffs_primar[teffs_primar>2000])
        spt_second[teffs_second>2000]= teff_to_spt_pecaut(teffs_second[teffs_second>2000])


        #compute combined binary spectral types
        xy=np.vstack([np.round(np.array(spt_primar), decimals=0), np.round(np.array(spt_second), decimals=0)]).T
        spt_binr=np.array(get_system_type(xy[:,0], xy[:,1])).astype(float)
        #Remember to assign <15 or >39 primary to primary and 
        out_range=np.logical_or(xy[:,0] < 15, xy[:,0] > 39)
        #print (spt_binr[out_range])
        spt_binr[out_range]=xy[:,0][out_range]


        values={ 'sing_evol': single_evol, 'sing_spt':spts_singl,
                     'prim_evol': primary_evol, 'prim_spt':spt_primar,
                     'sec_evol': secondary_evol, 'sec_spt': spt_second,
                    'binary_spt': spt_binr }

        #make systems
        # these dict values should be properties of the population object --> can be bad for mem, avoid duplicating data
        vals= _make_systems(values, self.binaryfraction).sample(n=int(self.nsample)).to_dict(orient='list')
        #add these values as attributes of the object
        for k, v in vals.items():
            setattr(self, k, v)

    def add_distances(self, gmodel, l, b, dmin, dmax, dsteps=1000):
        """
        Class for a poulation

        Attributes:
        ----
            x_grid: grid of values ( array)
            cdf:  corresponding values from the CDF
            nsample: optional, number of samples

        Properties:
        -------
            random draws

        Methods:
        --------

        Example:
        -------
            > x = np.arange(0, 10)
            > cdf = x**3/(x[-1]**3)
            > res= random_draw(x, cdf)

        """
        #gmodel = galactic component o
        #pick distances from 0.1pc to 10kpc at l=45 deg and b=0
        #case where l and b are floats
        l=np.array([l]).flatten()
        b=np.array([b]).flatten()
        assert len(l)== len(b)
        dists= np.concatenate([gmodel.sample_distances(dmin, dmax, \
        int(1.5*self.nsample/len(l)),l=l[idx], b=b[idx],  dsteps=dsteps ) for idx in range(len(l))])

        vals= {'l': l, 'b': b, 'distance': np.random.choice(dists, int(self.nsample))}

        for k, v in vals.items():
            setattr(self, k, v)

        self._distance=dists

    def add_magnitudes(self, filters, get_from='spt', **kwargs):
        """
        Class for a poulation

        Attributes:
        ----
            x_grid: grid of values ( array)
            cdf:  corresponding values from the CDF
            nsample: optional, number of samples

        Properties:
        -------
            random draws

        Methods:
        --------

        Example:
        -------
            > x = np.arange(0, 10)
            > cdf = x**3/(x[-1]**3)
            > res= random_draw(x, cdf)

        """
        if get_from=='spt':
            mags=pop_mags(np.array(self.spt), keys=filters, get_from='spt', **kwargs)
        
        if get_from=='teff':
            mags=pop_mags(np.array(self.temperature), keys=filters,  get_from='teff', **kwargs)

        if  self._distance is not None:
            for f in filters: mags[f] = mags['abs_{}'.format(f)].values+5*np.log10(self.distance/10.0)

        vals=mags.to_dict(orient='list')
        #add these values as attributes of the object
        for k, v in vals.items():
            setattr(self, k, v)

    def to_dataframe(self, columns):
        df=pd.DataFrame.from_records([self.__dict__[x] for x in  columns]).T
        df.columns=columns
        return df

    def visualize(self, keys=['mass', 'age', 'spt']):
        """
        Class for a poulation

        Attributes:
        ----
            x_grid: grid of values ( array)
            cdf:  corresponding values from the CDF
            nsample: optional, number of samples

        Properties:
        -------
            random draws

        Methods:
        --------

        Example:
        -------
            > x = np.arange(0, 10)
            > cdf = x**3/(x[-1]**3)
            > res= random_draw(x, cdf)

        """
        df=pd.DataFrame.from_records([self.__dict__[x] for x in  keys]).T
        df.columns=keys

        import matplotlib.pyplot as plt
        g = sns.PairGrid(df[keys] , diag_sharey=False, corner=True)
        g.map_diag(plt.hist, log=True, bins=32)
        g.map_offdiag(sns.scatterplot, size=0.1, color='k', alpha=0.1)

    def add_kinematics():
        raise NotImplementedError

    def apply_selection():
        #should delete previous entries to save space
        #selection should be a complex string --> sql to pass into series
        # must think about color-cuts
        #there must be a way to resample to nsample after making selection to not risk losing too many stars
        raise NotImplementedError



def _make_systems(mods, bfraction):
    
    #singles
    singles=mods['sing_evol']
    singles['is_binary']= np.zeros_like(mods['sing_spt']).astype(bool)
    singles['spt']=mods['sing_spt']
    singles['prim_spt']=mods['sing_spt']
    singles['sec_spt']=np.ones_like(mods['sing_spt'])*np.nan

    #print (np.isnan(singles['temperature']).all())
    
    #binary
    binaries={}
    binaries['age']=mods['prim_evol']['age']
    binaries['mass']=mods['prim_evol']['mass']+mods['sec_evol']['mass']
    binaries['pri_mass']=mods['prim_evol']['mass']
    binaries['sec_mass']=mods['sec_evol']['mass']
    
    binaries['luminosity']=np.log10(10**(mods['prim_evol']['luminosity']).value+\
    10**(mods['sec_evol']['luminosity']).value)
    #binaries['temperature']=mods['prim_evol']['temperature']
    binaries['spt']=np.random.normal(mods['binary_spt'], 0.3)
    binaries['prim_spt']=mods['prim_spt']
    binaries['sec_spt']=mods['sec_spt']
    binaries['prim_luminosity']=10**(mods['prim_evol']['luminosity']).value
    binaries['sec_luminosity']=10**(mods['sec_evol']['luminosity']).value

    binaries['is_binary']=np.ones_like(mods['sec_spt']).astype(bool)

    #assign teff from absolute mag
    #binaries['temperature']=get_teff_from_mag_ignore_unc(binaries['abs_2MASS_H'])
    mask= binaries['spt'] >20.
    binaries['temperature']= np.ones_like( binaries['spt'])*np.nan
    binaries['temperature'][mask]=spt_to_teff_kirkpatrick(binaries['spt'])[0][mask]
    binaries['temperature'][~mask]=spt_to_teff_pecaut(binaries['spt'])[~mask]

    #compute numbers to choose based on binary fraction
    ndraw= int(len(mods['sing_spt'])/(1-bfraction))-int(len(mods['sing_spt']))
    #ndraw=int(len(mods['sing_spt'])* bfraction)

    
    #random list of binaries to choose
    random_int=np.random.choice(np.arange(len(binaries['spt'])), ndraw)
    
    chosen_binaries={}
    for k in binaries.keys():
        chosen_binaries[k]=binaries[k][random_int]

    #add scale to the local lf
    res=pd.concat([pd.DataFrame(singles), pd.DataFrame(chosen_binaries)])
    scl=scale_to_local_lf(res.temperature.values)
    #print (scl
    res['scale']=scl[0]
    res['scale_unc']=scl[1]
    res['scale_times_model']=scl[-1]

    #combine the to dictionaries 
    #print (np.isnan(res['temperature']).all())

    return res

def pop_mags(x, d=None, keys=[], object_type='dwarfs', get_from='spt', reference=None, pol=None):
    """
    Compute magnitudes from pre-computed absolute mag relations

        Class for a poulation

        Attributes:
        ----
            x_grid: grid of values ( array)
            cdf:  corresponding values from the CDF
            nsample: optional, number of samples

        Properties:
        -------
            random draws

        Methods:
        --------

        Example:
        -------
            > x = np.arange(0, 10)
            > cdf = x**3/(x[-1]**3)
            > res= random_draw(x, cdf)

    """
    from .abs_mag_relations import POLYNOMIALS
    res={}
    if pol is None: pol=POLYNOMIALS['absmags_{}'.format(get_from)][object_type]
    if reference is not None: pol=POLYNOMIALS['references'][reference]
    for k in keys:
        #print (keys)
        #sometimes sds don't have absolute magnitudes defined 
        if k not in pol.keys():
            warnings.warn("{} relation not available for {} ".format(k,object_type))

        fit=np.poly1d(pol[k]['fit'])
        #scat=pol[k]['scatter'] #ignore scatter for now
        scat=0.1

        #print (k, 'scatter', scat)
        rng=pol[k]['range']
        mag_key=pol[k]['y']
        offset=pol[k]['x0']
        #put constraints on spt range
        mask= np.logical_and(x >rng[0], x <=rng[-1])
        absmag= np.random.normal(fit(x-offset),scat)
        #forget about scatter for now
        #absmag= fit(x-offset)

        masked_abs_mag= np.ma.masked_array(data=absmag, mask=~mask)
        #make it nans outside the range
        if d is not None: 
            res.update({ k: masked_abs_mag.filled(np.nan)+5*np.log10(d/10.0) })
        res.update({'abs_'+ k: masked_abs_mag.filled(np.nan)})


    return pd.DataFrame(res)

def pop_colors(x, d=None, keys=[], object_type='dwarfs', get_from='spt', reference=None, pol=None):
    """
    Compute colors from pre-computed absolute mag relations

        Class for a poulation

        Attributes:
        ----
            x_grid: grid of values ( array)
            cdf:  corresponding values from the CDF
            nsample: optional, number of samples

        Properties:
        -------
            random draws

        Methods:
        --------

        Example:
        -------
            > x = np.arange(0, 10)
            > cdf = x**3/(x[-1]**3)
            > res= random_draw(x, cdf)

    """
    from .abs_mag_relations import POLYNOMIALS
    res={}
    if pol is None: pol=POLYNOMIALS['colors_{}'.format(get_from)][object_type]
    if reference is not None: pol=POLYNOMIALS['references'][reference]
    for k in keys:
        #sometimes sds don't have absolute magnitudes defined 
        if k not in pol.keys():
            warnings.warn("{} relation not available for {} ".format(k,object_type))

        #if pol[k]['method']=='polynmial':
        fit=np.poly1d(pol[k]['fit'])
        #if pol[k]['method']=='spline':
        #     fit=pol[k]['fit']

        scat=pol[k]['scatter']
        
        rng=pol[k]['range']
        mag_key=pol[k]['y']
        offset=pol[k]['x0']
        #put constraints on spt range
        mask= np.logical_and(x >rng[0], x <=rng[-1])
        absmag= np.random.normal(fit(x-offset),scat)

        masked_abs_mag= np.ma.masked_array(data=absmag, mask=~mask)

        res.update({ mag_key:masked_abs_mag.filled(np.nan)})

    return pd.DataFrame(res)
