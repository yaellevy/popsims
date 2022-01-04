

################################
#population simulations routines
#includes copied functions from splat
##############################
import numpy as np
import numba
import scipy
from .tools import random_draw, compute_pm_from_uvw
import scipy.integrate as integrate
from .core import make_systems
from scipy.interpolate import interp1d
import pandas as pd
from astropy.coordinates import SkyCoord
import astropy.coordinates as astro_coord
import astropy.units as u
import warnings
import gala.coordinates as gc
import gala.dynamics as gd
import collections
from tqdm import tqdm

#some constants
MAG_KEYS=['WFIRST_WFIJ', 'WFIRST_WFIH', 'WFIRST_WFIK', 'WFIRST_WFIY', 'WFIRST_WFIZ']
POLYNOMIALS=pd.read_pickle(DATA_FOLDER+'/absmag_relations.pkl')

Rsun=8300.
Zsun=27.

_ = astro_coord.galactocentric_frame_defaults.set('v4.0')
#galactocentric reference frame
v_sun = astro_coord.CartesianDifferential([11.1, 220 + 24.0, 7.25]*u.km/u.s)

galcen_frame =astro_coord.Galactocentric(galcen_distance=8.3*u.kpc,
                                    galcen_v_sun=v_sun)

def galactic_density(rd, zd, Hthin=350, Hthick=900):
    fh=0.0051
    ft=0.12
    #only change thin disk scaleheight, keep thick disk and halo fixed
    thin=exponential_density(rd, zd, Hthin, 2600)
    thick=exponential_density(rd, zd, Hthick, 3600)
    halo=spheroid_density(rd, zd)
    return {'thin': thin, 'thick': ft*thick , 'halo': fh*halo}

def transform_tocylindrical(l, b, ds):
    rd=np.sqrt( (ds * np.cos( b ) )**2 + Rsun * (Rsun - 2 * ds * np.cos( b ) * np.cos( l ) ) )
    zd=Zsun+ ds * np.sin( b - np.arctan( Zsun / Rsun) )
    return (rd, zd)

class Pointing(object):
    ## a pointing object making it easier to draw samples
    def __init__(self, **kwargs):
        #only input is the direction
        self.coord=kwargs.get('coord', None)
        self.survey=kwargs.get('survey', None)
        self.name=kwargs.get('name', None)
        self._mag_limits=kwargs.get('mag_limits', None)
        self.area=kwargs.get('area', None)
        self._dist_limits={}
        self._volume={}
        self.distance_cdf={}
        self.dens_profile=kwargs.get('density', 'exp')

    @property
    def volume(self):
        return self._volume

    @property
    def distance_limits(self):
        return self._dist_limits

    @property
    def mag_limits(self):
        return self._mag_limits

    @mag_limits.setter
    def mag_limits(self, new_lts):
        self._mag_limits=new_lts
        #compute distance limits for each 
        for k in new_lts.keys():
            ds={}
            for s in np.arange(10, 43):
                pol=POLYNOMIALS['absmags']['dwarfs'][k]['fit']
                dmin= get_distance(pol(s), new_lts[k][0])
                dmax= get_distance(pol(s), new_lts[k][1])
                ds.update({s: [dmin, dmax]})

            self._dist_limits.update({k: ds})


    def draw_distances(self, dmin, dmax, scaleH, scaleL, nsample=1e3):
        ##draw random distances in this direction for a specific spectral type
        d=np.logspace(np.log10(dmin), np.log10(dmax), int(nsample))
        #print (d, dmin, dmax)
        if not 'h{}l{}'.format(scaleH, scaleL) in self.distance_cdf.keys():
            self.distance_cdf['h{}l{}'.format(scaleH, scaleL)]=interpolated_cdf(self.coord.galactic.l.radian, \
                   self.coord.galactic.b.radian, scaleH, scaleL, kind=self.dens_profile)

        cdfvals=self.distance_cdf['h{}l{}'.format(scaleH, scaleL)](d)
        return random_draw(d, cdfvals/np.nanmax(cdfvals), int(nsample))
        


def pop_mags_from_type(spt, d=None, keys=[], object_type='dwarfs', reference=None):
    """
    SPT is an array of spectral types from a Monte Carlo sampling
    """
    res={}
    pol=POLYNOMIALS['absmags'][object_type]
    if reference is not None: pol=POLYNOMIALS['references'][reference]
    for k in keys:
        #sometimes sds don't have absolute magnitudes defined 
        if k not in pol.keys():
            warnings.warn("Key not available for {} using {} instead".format(object_type, 'dwarfs'))
            object_type='dwarfs'
            pol=POLYNOMIALS['absmags'][object_type]

        fit=pol[k]['fit']
        scat=pol[k]['scatter']
        rng=pol[k]['range']
        mag_key=pol[k]['y']
        offset=pol[k]['x0']
        absmag= np.random.normal(fit(spt-offset),scat)
        #make it nans outside the range
        absmag[np.logical_and(spt <rng[0], spt <rng[-1])]=np.nan
        if d is not None: res.update({ mag_key: absmag+5*np.log10(d/10.0) })
        res.update({'abs_'+ mag_key: absmag})

    return pd.DataFrame(res)

def pop_mags_from_color(color, d=None, keys=[], object_type='dwarfs'):
    """
    color is an array of colors from a Monte Carlo sampling
    """
    res={}
    for k in tqdm(keys):
        pol=POLYNOMIALS['colors'][object_type]
        fit=pol[k]['fit']
        scat=pol[k]['scatter']
        rng=pol[k]['range']
        mag_key=pol[k]['y']
        absmag= np.random.normal(fit(color),scat)
        #make it nans outside the range
        absmag[np.logical_and(color <rng[0], color <rng[-1])]=np.nan
        if d is not None: res.update({ mag_key: absmag+5*np.log10(d/10.0) })
        res.update({'abs_'+ mag_key: absmag})

    return pd.DataFrame(res)



def interpolated_cdf(l, b, scaleH, scaleL, **kwargs):
    #interpolated cdf up a further distance to avoid using each time I have to draw a distance
    d=np.concatenate([[10**-2], np.logspace(-1, 6, int(1e4))])
    #print (d)
    cdfvals=np.array([volume_calc(l,b,0, dx, scaleH,scaleL, **kwargs) for dx in d])
    #remove nans and infinities
    cdfvals= cdfvals/np.nanmax(cdfvals)
    bools= np
    return interp1d(d, cdfvals)

def exponential_density(r, z, H,L):
    """
        expoential galactic density porfile
    """
    zpart=np.exp(-abs(z-Zsun)/H)
    rpart=np.exp(-(r-Rsun)/L)
    return zpart*rpart

def spheroid_density(r, z):
    """
        Spheroid density profile
    """
    q = 0.64 #: halo axial ratio
    n = 2.77#: spherical power law index
    return  (Rsun/(((r)**2+((z)/q)**2)**0.5))**n

@numba.vectorize("float64(float64, float64)", target='cpu')
def get_distance(absmag, rel_mag):
    return 10.**(-(absmag-rel_mag)/5. + 1.)
    
def avr_aumer(sigma,  direction='vertical', verbose=False):
    #return the age from an age-velocity dispersion 
    verboseprint = print if verbose else lambda *a, **k: None
    result=None
    beta_dict={'radial': [0.307, 0.001, 41.899],
                'total': [ 0.385, 0.261, 57.15747],
                'azimuthal':[0.430, 0.715, 28.823],
                'vertical':[0.445, 0.001, 23.831],
                }

    verboseprint("Assuming Aumer & Binney 2009 Metal-Rich Fits and {} velocity ".format(direction))

    beta, tau1, sigma10=beta_dict[direction]
       
    result=((sigma/sigma10)**(1/beta))*(10+tau1)-tau1

    return result

def avr_yu(sigma, verbose=False, disk='thin', direction='vertical', height='above', nsample=1e4):
    verboseprint = print if verbose else lambda *a, **k: None
    #the dictionary has thin disk and thick disk
    #thin disk  AVR is for [Fe<H] <-0.2 and two different fits for 
    #|z| > 270 pc and |z|<270
    _, tau1, sigma10= 0.385, 0.261, 57.15747
    
    beta_dict={'thin':{'vertical': [[0.54, 0.13], [0.48, 0.14]],
              'azimuthal':[[0.30, 0.09],[0.4, 0.12]],
              'radial': [ [0.28, 0.08], [0.36, 0.28]]},
               'thick':{'vertical': [[0.56, 0.14], [0.51, 0.15]],
              'azimuthal':[[0.34, 0.12],[0.42, 0.14]],
              'radial': [ [0.34, 0.17], [0.39, 0.13]]}}
    
    beta=beta_dict[disk][direction][0]
    if  height=='below':
         beta=beta_dict[disk][direction][1]
    if height=='median':
        vals=np.array([beta_dict[disk][direction][0], beta_dict[disk][direction][1]])
        beta=[(vals[:,0]).mean(), (vals[:,1]**2).sum()**0.5]
    verboseprint("Assuming Yu & Liu 2018, {} disk {} velocities ".format(disk, direction))
    if np.isscalar(sigma):
        betas=(np.random.normal(beta[0], beta[-1], int(nsample)))
        #sigmas= sigma**(np.random.normal(beta[0], beta[-1], 10000))
        #sigmas=((sigma/sigma10)**(1/betas))*(10+tau1)-tau1
        sigmas= sigma**(betas)
        return np.nanmedian(sigmas), np.nanstd(sigmas)
    else:
        betas=(np.random.normal(beta[0], beta[-1], (int(nsample), len(sigma))))
        #sigmas= sigma**(np.random.normal(beta[0], beta[-1], 10000))
        #sigmas=((sigma/sigma10)**(1/betas))*(10+tau1)-tau1
        sigmas= sigma**(betas)
        #sigmas= sigma**(np.random.normal(beta[0], beta[-1], (10000, len(sigma))))
        return np.vstack([np.nanmedian(sigmas, axis=0), np.nanstd(sigmas, axis=0)])

def avr_sanders(sigma, verbose=False, direction='vertical'):
    #return the age from an age-velocity dispersion 
    verboseprint = print if verbose else lambda *a, **k: None
    beta_dict={'radial': 0.3, 'vertical': 0.4}
    beta=beta_dict[direction]
    verboseprint("Assuming Sanders et al. 2018 Power for  velocity {}".format(direction))
    return sigma**(beta)

def avr_just(sigma, verbose=False, direction='vertical'):
    #return the age from an age-velocity dispersion 
    verboseprint = print if verbose else lambda *a, **k: None
    beta_dict={'radial': None, 'vertical': 0.375, 'azimuthal': None}
    beta=beta_dict[direction]
    verboseprint("Just et al. 2010 power law for  velocity {}".format(direction))
    sigma0, t0, tp, alpha=(25, 0.17, 12, 0.375)
    return ((sigma/sigma0)**(1/alpha))*(tp+t0)-t0

def scaleheight_to_vertical_disp(hs):
    shape=277 #shape parameter
    sigma_68=1.
    return np.sqrt((np.array(hs))/shape)*20

def volume_calc(l,b,dmin, dmax, scaleH, scaleL, kind='exp'):
    nsamp=1000
    fh=0.0051
    ds = np.linspace(dmin,dmax,nsamp)
    rd=np.sqrt( (ds * np.cos( b ) )**2 + Rsun * (Rsun - 2 * ds * np.cos( b ) * np.cos( l ) ) )
    zd=Zsun+ ds * np.sin( b - np.arctan( Zsun / Rsun) )
    rh0=exponential_density(rd, zd, scaleH, scaleL)
    if kind =='spheroid':
         rh0=spheroid_density(rd, zd)
    if kind=='both':
        rh0= rh0+fh*spheroid_density(rd, zd)
    val=integrate.trapz(rh0*(ds**2), x=ds)
    return val

def get_velocities(age, kind='thin_disk',z=None):
    #velocity paremeters
    #returns simple gaussians from velocity dispersions
    
    v10 = 41.899
    tau1 = 0.001
    beta = 0.307

    v10_v = 28.823
    tau_v = 0.715
    beta_v = 0.430

    v10_w = 23.381
    tau_w = 0.001
    beta_w = 0.445

    k = 74.
    sigma_u = v10*((age+tau1)/(10.+tau1))**beta
    sigma_v =  v10_v*((age+tau_v)/(10.+tau_v))**beta_v
    sigma_w =  v10_w*((age+tau_w)/(10.+tau_w))**beta_w

    voff = -1.*(sigma_v**2)/k

    us=np.random.normal(loc=0, scale=sigma_u, size=len(age))
    vs =np.random.normal(loc=voff, scale=sigma_v, size=len(age))
    ws =np.random.normal(loc=0.0, scale=sigma_w, size=len(age))
    vels={'U': us, 'V':vs,  'W':ws }
    if kind=='halo':
        #values from carollo et al. not exactly right but close
        #these are actually vr, vphi, vz
        vr=np.random.normal(loc=3, scale=150, size=len(age))
        vphi=np.random.normal(loc=7, scale=95, size=len(age))
        vz=np.random.normal(loc=3, scale=85, size=len(age))
        vels={'Vr': vr, 'Vphi':vphi,  'Vz':vz }
        
    if kind=='thick_disk':
        #use Bensby et al
        v_assym=46
        uvw_lsr=[0, 0, 0]
        us=np.random.normal(loc=uvw_lsr[0], scale=67,size=len(age))
        vs=np.random.normal(loc=uvw_lsr[1]-v_assym, scale=38,size=len(age))
        ws=np.random.normal(loc=uvw_lsr[-1], scale=35,size=len(age))
        vels={'U': us, 'V':vs,  'W':ws }
    
    return  pd.DataFrame(vels)

def get_proper_motion(ra, dec, d, u, v, w):
    
    motions=compute_pm_from_uvw(ra, dec,d, u, v, w,\
                               correct_lsr=False)
    return pd.Series({'RV':  motions[0] ,\
                      'mu_alpha': motions[1],\
                      'mu_delta': motions[2],
                      'Vtan': motions[-1]})

def get_proper_motion_cylindrical(ra,dec, d, vr, vphi, vz):
    
    """
    vphi must be in rad/s not km/s
    ra, dec in deg and distance in kpc
    
    """
    
    c=astro_coord.CylindricalDifferential(d_rho=vr*u.km/u.s,\
                                      d_phi=(vphi*u.rad/u.s).to(u.deg/u.s),\
                                      d_z=vz*u.km/u.s)

    co=astro_coord.SkyCoord(ra=ra*u.degree, dec=dec*u.degree, \
                       distance=d*u.kpc).transform_to(galcen_frame ).cylindrical
    
    c.to_cartesian(co)
    co.to_cartesian()
    xyz = astro_coord.SkyCoord(x=co.to_cartesian().x, 
                               y=co.to_cartesian().y, \
                               z=co.to_cartesian().z, frame=galcen_frame)
    vxyz = [c.to_cartesian(co).x.to(u.km/u.s).value,\
     c.to_cartesian(co).y.to(u.km/u.s).value, \
     c.to_cartesian(co).z.to(u.km/u.s).value]*u.km/u.s
    
    w = gd.PhaseSpacePosition(pos=xyz.cartesian.xyz, vel=vxyz)
    gal_c = w.to_coord_frame(astro_coord.ICRS)
    
  
    return {'RV': gal_c.radial_velocity ,\
                      'mu_alpha':gal_c.pm_ra_cosdec/np.cos(dec*u.degree),\
                      'mu_delta': gal_c.pm_dec}


def create_pop(bfraction=None,\
                     model=None,  nsample=None,
                     dmax=None, l=None, b=None, \
               absmag_keys=['WFIRST_WFIJ'], 
              population='thin_disk', distances=None, poptype='dwarfs'):
    
    mass_age_ranges={'thin_disk':[0.01, 0.15, 0., 8.0],\
                    'thick_disk': [0.01, 0.15, 8., 13.0],\
                    'halo':[0.01, 0.15, 10., 13.0]}
    #get fundamental parameters
    df=make_systems(model=model, bfraction=bfraction,\
                            mass_age_range= mass_age_ranges[population],\
                                nsample=nsample,
                                recompute=True)
    #trim to desired types to reduce size of dataframe
    #df=(df[df.spt.between(grid[0], grid[-1])]).reset_index(drop=True)
    ls=l
    bs=b

    if isinstance(l, collections.Sequence): 
        ls= np.random.choice(l, len(df))
    if isinstance(b, collections.Sequence): 
        bs= np.random.choice(b, len(df))
    
    #assign distances and directions
    df['d']= np.random.choice(distances, len(df))
    df['l']= ls
    df['b']= bs
    #computer r and z
    r, z=transform_tocylindrical(df.l.values, df.b.values, df.d.values)
    df['r']=r
    df['z']=z
    #get velocities  and add magnitude
    if population != 'halo':
        vels=get_velocities(df.age, z= df.z, kind=population).reset_index(drop=True)
        #compute proper motions
    
    if population == 'halo':
        vels= get_velocities(df.age, z= df.z, kind=population).reset_index(drop=True)
        #use astropy to computer proper motions #no need to compute at this stage
       
    dff=pop_mags_from_type(df.spt.values, d=df.d.values, \
            keys=absmag_keys, object_type=poptype).join(df).join(vels)

    return dff