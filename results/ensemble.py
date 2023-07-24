import os
import numpy as np
import pandas as pd
import utils
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import cartopy.crs as ccrs
import math
from datetime import datetime, timedelta


def load_ensemble(working_dir, n_members, params):
    """
    Loads the results of an ensemble

    Args:
        working_dir (str): filepath to the root of the ensemble
        n_members (int): number of members in the ensemble
        params (list): parameters (str) predicted by the model

    Returns:
        DataFrame: a dataframe that contains all the members for all the parameters in the ensemble
    """
    ens_df = pd.DataFrame(
        [],
        columns = []
    )

    for i_m in range(n_members):
        path = os.path.join(
            working_dir, str(i_m + 1), "y_pred.csv"
        )
        y_m = pd.read_pickle(path)
        if i_m == 0:
            y_m = y_m.rename(columns={p:p + "_" + str(i_m + 1) for p in params})
        else:
            y_m = y_m.rename(columns={p:p + "_" + str(i_m + 1) for p in params}).drop(columns=["dates", "echeances"])
        
        ens_df = pd.concat([ens_df, y_m], axis=1)
    
    return ens_df


def load_ensemble_arome(dates, echeances, params, n_members, data_location):
    """
    Loads a dataframe containing results of a PE-Arome ensemble (2,5km)

    Args:
        dates (list): list of dates (str)
        echeances (list): list of echeances (int)
        params (list): list of parameters
        n_members (int): number of members
        data_location (str): filepath to directory containing .npy files

    Returns:
        DataFrame: dataframe containing all the needed fields
    """
    ens_df = pd.DataFrame(
        [], 
        columns = ['dates', 'echeances'] + [p + "_" + str(j + 1) for p in params for j in range(n_members)]
    )
    domain_shape = utils.get_shape_2km5()
    
    for i_d, d in enumerate(dates):
        ens_d = np.zeros((n_members, len(echeances), domain_shape[0], domain_shape[1], len(params)))
        # charger tous les membres de tous les paramètres
        try:
            for i_m in range(n_members):
                for i_p, p in enumerate(params):
                    filepath = data_location + str(i_m + 1) + '/GC81_' + d + 'Z_' + p + '.npy'
                    ens_d[i_m, :, :, :, i_p] = np.load(filepath).transpose([2, 0, 1])
        except FileNotFoundError:
            print('missing day : ' + d)
            ens_d = None
        
        if ens_d is not None:
            for i_ech, ech in enumerate(echeances):
                values = [ens_d[i_m, i_ech, :, :, i_p] for i_p in range(len(params)) for i_m in range(n_members)]
                ens_df.loc[len(ens_df)] = [d, ech] + values
        
    return ens_df


def correct_dates_for_arome(arome_ens_df):
    """
    Corrects dates for the real Arome ensemble

    Args:
        arome_ens_df (DataFrame): Arome ensemble data loaded with load_ensemble_arome()

    Returns:
        DataFrame: dataframe with corrected dates and echeances (to match the situations with the ddpm ensemble)
    """
    arome_ens_corrected = pd.DataFrame(
        [],
        columns=arome_ens_df.columns
    )
    channels = utils.get_arrays_cols(arome_ens_df)
    delta = timedelta(hours = 6)
    for i in range(len(arome_ens_df)):
        values = [arome_ens_df[channels[j]].iloc[i] for j in range(len(channels))]
        date_ech = [
            (datetime.fromisoformat(arome_ens_df.dates.iloc[i]) + delta).isoformat(),
            arome_ens_df.echeances.iloc[i] - 6
        ]
        arome_ens_corrected.loc[len(arome_ens_corrected)] = date_ech + values 
    return arome_ens_corrected


def group_ensembles(arome_df, ddpm_df):
    """
    Groups two DataFrame containing ensemble samples / stats into a single DataFrame
    """
    unique_df = pd.DataFrame(
        [],
        columns=[]
    )

    unique_df = ddpm_df.merge(arome_df, how="outer", on=["dates", "echeances"], suffixes=("_ddpm", "_arome"))

    return unique_df.dropna().reset_index(drop=True)


def plot_maps_ensemble(ens_df, output_dir, param, unit, n_members, n=42, cmap="viridis"):
    """
    Plots fields given by each member of the ensemble

    Args:
        ens_df (DataFrame): dataframe containing the fields predicted by the model
        output_dir (str): output directory
        param (str): parameter to plot
        unit (str): unit of the considered parameter
        n_members (int): number of members
        n (int, optional): number of images to plot. Defaults to 10.
        cmap (str, optional): colormap. Defaults to "viridis".
    """
    k = math.floor(math.sqrt(n_members)) + 1 # size of the figure (number of plots / side)
    for i in range(n):
        fig = plt.figure(figsize=[5*k, 4*k])
        axs = []
        for j in range(n_members):
            axs.append(fig.add_subplot(k, k, j+1, projection=ccrs.PlateCarree()))
            axs[j].set_extent(utils.IMG_EXTENT)
            axs[j].coastlines(resolution='10m', color='black', linewidth=1)

        data = [ens_df[param + "_" + str(j + 1)].iloc[i] for j in range(n_members)]
        images = []
        for j in range(n_members):
            images.append(axs[j].imshow(data[j], cmap=cmap, origin='upper', extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree()))
            axs[j].label_outer()
            axs[j].set_title(str(j + 1), fontdict={"fontsize": 20})
        vmin = min(image.get_array().min() for image in images)
        vmax = max(image.get_array().max() for image in images)
        norm = colors.Normalize(vmin=vmin, vmax=vmax)
        for im in images:
            im.set_norm(norm)
        
        fig.colorbar(images[0], ax=axs, label="{} [{}]".format(param, unit))
        plt.savefig(output_dir + 'results_' + str(i) + '_' + param + '.png', bbox_inches='tight')


def compute_pointwise_mean(ens_df, n_members, params_out):
    """
    Returns a dataframe containing arrays of pointwise means for each sample in the ensemble

    Args:
        ens_df (DataFrame): dataframe containing results
        n_members (int): number of members in the ensemble
        params_out (list): parameters (str) predicted by the model

    Returns:
        DataFrame: a dataframe containing all the pointwise mean maps in the ensemble for each sample
    """
    stat_df = pd.DataFrame(
        [],
        columns=["dates", "echeances"] + [p for p in params_out]
    )
    for i in range(len(ens_df)):
        values = []
        for i_p, p in enumerate(params_out):
            array_p = np.array([ens_df[p + "_" + str(j + 1)].iloc[i] for j in range(n_members)])
            values.append(array_p.mean(axis=0))
        stat_df.loc[len(stat_df)] = [ens_df.dates.iloc[i], ens_df.echeances.iloc[i]] + values
    return stat_df


def compute_pointwise_std(ens_df, n_members, params_out):
    """
    Returns a dataframe containing arrays of pointwise means for each sample in the ensemble

    Args:
        ens_df (DataFrame): dataframe containing results
        n_members (int): number of members in the ensemble
        params_out (list): parameters (str) predicted by the model

    Returns:
        DataFrame: a dataframe containing all the pointwise std maps in the ensemble for each sample
    """
    stat_df = pd.DataFrame(
        [],
        columns=["dates", "echeances"] + [p for p in params_out]
    )
    for i in range(len(ens_df)):
        values = []
        for i_p, p in enumerate(params_out):
            array_p = np.array([ens_df[p + "_" + str(j + 1)].iloc[i] for j in range(n_members)])
            values.append(array_p.std(axis=0))
        stat_df.loc[len(stat_df)] = [ens_df.dates.iloc[i], ens_df.echeances.iloc[i]] + values
    return stat_df


def compute_pointwise_Q5(ens_df, n_members, params_out):
    """
    Returns a dataframe containing arrays of pointwise Q5 for each sample in the ensemble

    Args:
        ens_df (DataFrame): dataframe containing results
        n_members (int): number of members in the ensemble
        params_out (list): parameters (str) predicted by the model

    Returns:
        DataFrame: a dataframe containing all the pointwise Q5 maps in the ensemble for each sample
    """
    stat_df = pd.DataFrame(
        [],
        columns=["dates", "echeances"] + [p for p in params_out]
    )
    for i in range(len(ens_df)):
        values = []
        for i_p, p in enumerate(params_out):
            array_p = np.array([ens_df[p + "_" + str(j + 1)].iloc[i] for j in range(n_members)])
            values.append(np.percentile(array_p, 5, axis=0))
        stat_df.loc[len(stat_df)] = [ens_df.dates.iloc[i], ens_df.echeances.iloc[i]] + values
    return stat_df


def compute_pointwise_Q95(ens_df, n_members, params_out):
    """
    Returns a dataframe containing arrays of pointwise Q95 for each sample in the ensemble

    Args:
        ens_df (DataFrame): dataframe containing results
        n_members (int): number of members in the ensemble
        params_out (list): parameters (str) predicted by the model

    Returns:
        DataFrame: a dataframe containing all the pointwise Q95 maps in the ensemble for each sample
    """
    stat_df = pd.DataFrame(
        [],
        columns=["dates", "echeances"] + [p for p in params_out]
    )
    for i in range(len(ens_df)):
        values = []
        for i_p, p in enumerate(params_out):
            array_p = np.array([ens_df[p + "_" + str(j + 1)].iloc[i] for j in range(n_members)])
            values.append(np.percentile(array_p, 95, axis=0))
        stat_df.loc[len(stat_df)] = [ens_df.dates.iloc[i], ens_df.echeances.iloc[i]] + values
    return stat_df


def plot_stat_ensemble(stat_df, output_dir, stat, param, unit, n=42, cmap="viridis"):
    """
    Plots a statistic map (mean, std, Q5, Q95) for n samples

    Args:
        stat_df (DataFrame): dataframe containing the statistic to plot
        output_dir (str): output directory
        stat (str): name of the statistic
        param (str): studied parameter
        unit (str): unit
        n (int, optional): number of figures to make. Defaults to 42.
        cmap (str, optional): colormap. Defaults to "viridis".
    """
    for i in range(n):
        fig = plt.figure(figsize=[20, 16])
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        ax.set_extent(utils.IMG_EXTENT)
        ax.coastlines(resolution='10m', color='black', linewidth=1)
        im = ax.imshow(stat_df[param].iloc[i], cmap=cmap, origin='upper', extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
        
        fig.colorbar(im, ax=ax, label="{} {} [{}]".format(stat, param, unit))
        plt.savefig(output_dir + stat + '_' + str(i) + '_' + param + '.png', bbox_inches='tight')


def plot_all_stats_ensemble(mean_df, std_df, Q5_df, Q95_df, output_dir, param, n=42):
    """
    Plots all the statistics on the same figure.

    Args:
        mean_df (DataFrame): a dataframe that contains the mean values
        std_df (DataFrame): a dataframe that contains the std values
        Q5_df (DataFrame): a dataframe that contais the Q5 values
        Q95_df (DataFrame): a dataframe that contains the Q95 values
        output_dir (st): output directory
        param (str): studied parameter
        n (int, optional): number of samples to plot. Defaults to 42.
    """
    all_stats_df = pd.DataFrame(
        [],
        columns = []
    )
    all_stats_df = pd.concat([all_stats_df, mean_df[["dates", "echeances"]]], axis=1)
    all_stats_df = pd.concat([all_stats_df, mean_df[[param]].rename(columns={param:param + "_mean"})], axis=1)
    all_stats_df = pd.concat([all_stats_df,  std_df[[param]].rename(columns={param:param + "_std"})], axis=1)
    all_stats_df = pd.concat([all_stats_df,   Q5_df[[param]].rename(columns={param:param + "_Q5"})], axis=1)
    all_stats_df = pd.concat([all_stats_df,  Q95_df[[param]].rename(columns={param:param + "_Q95"})], axis=1)

    for i in range(n):
        fig = plt.figure(figsize=[25, 5])
        axs = []
        for j in range(4):
            axs.append(fig.add_subplot(1, 4, j+1, projection=ccrs.PlateCarree()))
            axs[j].set_extent(utils.IMG_EXTENT)
            axs[j].coastlines(resolution='10m', color='black', linewidth=1)

        images = []

        im = axs[0].imshow(all_stats_df[param + "_mean"].iloc[i], cmap="viridis", origin='upper', 
                           extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
        images.append(im)
        axs[0].label_outer()
        im = axs[1].imshow(all_stats_df[param + "_std"].iloc[i], cmap="plasma", origin='upper', 
                           extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
        fig.colorbar(im, ax=axs[1])
        im = axs[2].imshow(all_stats_df[param + "_Q5"].iloc[i], cmap="viridis", origin='upper', 
                           extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
        images.append(im)
        axs[2].label_outer()
        im = axs[3].imshow(all_stats_df[param + "_Q95"].iloc[i], cmap="viridis", origin='upper', 
                           extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
        images.append(im)
        axs[3].label_outer()        
        
        vmin = min(image.get_array().min() for image in images)
        vmax = max(image.get_array().max() for image in images)
        norm = colors.Normalize(vmin=vmin, vmax=vmax)
        for im in images:
            im.set_norm(norm)

        fig.colorbar(images[0], ax=axs[0])
        fig.colorbar(images[0], ax=axs[2])
        fig.colorbar(images[0], ax=axs[3])

        axs[0].set_title("mean")
        axs[1].set_title("std")
        axs[2].set_title("Q5")
        axs[3].set_title("Q95")

        plt.savefig(output_dir + 'all_stats_' + str(i) + '_' + param + '.png', bbox_inches='tight')


def plot_unique_all_stats_ensemble(mean_df, std_df, Q5_df, Q95_df, output_dir, param):
    """
    Plots all the statistics on the same figure (pointwise mean for all the samples)

    Args:
        mean_df (DataFrame): a dataframe that contains the mean values
        std_df (DataFrame): a dataframe that contains the std values
        Q5_df (DataFrame): a dataframe that contais the Q5 values
        Q95_df (DataFrame): a dataframe that contains the Q95 values
        output_dir (st): output directory
        param (str): studied parameter
    """
    all_stats_df = pd.DataFrame(
        [],
        columns = []
    )
    all_stats_df = pd.concat([all_stats_df, mean_df[["dates", "echeances"]]], axis=1)
    all_stats_df = pd.concat([all_stats_df, mean_df[[param]].rename(columns={param:param + "_mean"})], axis=1)
    all_stats_df = pd.concat([all_stats_df,  std_df[[param]].rename(columns={param:param + "_std"})], axis=1)
    all_stats_df = pd.concat([all_stats_df,   Q5_df[[param]].rename(columns={param:param + "_Q5"})], axis=1)
    all_stats_df = pd.concat([all_stats_df,  Q95_df[[param]].rename(columns={param:param + "_Q95"})], axis=1)

    fig = plt.figure(figsize=[25, 5])
    axs = []
    for j in range(4):
        axs.append(fig.add_subplot(1, 4, j+1, projection=ccrs.PlateCarree()))
        axs[j].set_extent(utils.IMG_EXTENT)
        axs[j].coastlines(resolution='10m', color='black', linewidth=1)

    images = []

    im = axs[0].imshow(all_stats_df[param + "_mean"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[0].label_outer()
    im = axs[1].imshow(all_stats_df[param + "_std"].mean(), cmap="plasma", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    fig.colorbar(im, ax=axs[1])
    im = axs[2].imshow(all_stats_df[param + "_Q5"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[2].label_outer()
    im = axs[3].imshow(all_stats_df[param + "_Q95"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[3].label_outer()        
    
    vmin = min(image.get_array().min() for image in images)
    vmax = max(image.get_array().max() for image in images)
    norm = colors.Normalize(vmin=vmin, vmax=vmax)
    for im in images:
        im.set_norm(norm)

    fig.colorbar(images[0], ax=axs[0])
    fig.colorbar(images[0], ax=axs[2])
    fig.colorbar(images[0], ax=axs[3])

    axs[0].set_title("mean")
    axs[1].set_title("std")
    axs[2].set_title("Q5")
    axs[3].set_title("Q95")

    plt.savefig(output_dir + 'all_stats_unique_' + param + '.png', bbox_inches='tight')


def plot_stat_distrib(mean_df, std_df, Q5_df, Q95_df, output_dir, param):
    
    D = np.zeros((len(mean_df), 3))
    for i in range(len(mean_df)):
        D[i, 0] = mean_df[param].iloc[i].mean()
        D[i, 1] = Q5_df[param].iloc[i].mean()
        D[i, 2] = Q95_df[param].iloc[i].mean()
    labels = ['mean', 'Q5', 'Q95']

    D_std = np.zeros((len(mean_df), 1))
    for i in range(len(mean_df)):
        D_std[i, 0] = std_df[param].iloc[i].mean()
    labels_std = ['std']

    
    fig, axs = plt.subplots(nrows=1, ncols=2, figsize=(20, 7))
    axs[0].grid()
    VP = axs[0].boxplot(D, positions=[3, 6, 9], widths=1.5, patch_artist=True,
                    showmeans=True, meanline=True, showfliers=False,
                    medianprops={"color": "white", "linewidth": 0.5},
                    boxprops={"facecolor": "C0", "edgecolor": "white",
                            "linewidth": 0.5},
                    whiskerprops={"color": "C0", "linewidth": 1.5},
                    capprops={"color": "C0", "linewidth": 1.5},
                    meanprops = dict(linestyle='--', linewidth=2.5, color='purple'),
                    labels=labels)
    axs[0].tick_params(axis='x', rotation=45)

    axs[1].grid()
    VP = axs[1].boxplot(D_std, positions=[3], widths=0.2, patch_artist=True,
                    showmeans=True, meanline=True, showfliers=False,
                    medianprops={"color": "white", "linewidth": 0.5},
                    boxprops={"facecolor": "C0", "edgecolor": "white",
                            "linewidth": 0.5},
                    whiskerprops={"color": "C0", "linewidth": 1.5},
                    capprops={"color": "C0", "linewidth": 1.5},
                    meanprops = dict(linestyle='--', linewidth=2.5, color='purple'),
                    labels=labels_std)
    axs[1].tick_params(axis='x', rotation=45)

    plt.savefig(output_dir + 'distribution.png')


def synthesis_unique_all_stats_ensemble(
    mean_df,
    std_df,
    Q5_df,
    Q95_df,
    output_dir,
    param,

):
    all_stats_df = pd.DataFrame(
        [],
        columns = []
    )
    all_stats_df = pd.concat([all_stats_df, mean_df[["dates", "echeances"]]], axis=1)
    all_stats_df = pd.concat([all_stats_df, mean_df[[param + m for m in ["_arome", "_ddpm"]]].rename(columns={param+ m:param + m + "_mean" for m in ["_arome", "_ddpm"]})], axis=1)
    all_stats_df = pd.concat([all_stats_df,  std_df[[param + m for m in ["_arome", "_ddpm"]]].rename(columns={param+ m:param + m + "_std" for m in ["_arome", "_ddpm"]})], axis=1)
    all_stats_df = pd.concat([all_stats_df,   Q5_df[[param + m for m in ["_arome", "_ddpm"]]].rename(columns={param+ m:param + m + "_Q5" for m in ["_arome", "_ddpm"]})], axis=1)
    all_stats_df = pd.concat([all_stats_df,  Q95_df[[param + m for m in ["_arome", "_ddpm"]]].rename(columns={param+ m:param + m + "_Q95" for m in ["_arome", "_ddpm"]})], axis=1)

    fig = plt.figure(figsize=[25, 11])
    axs = []
    for j in range(8):
        axs.append(fig.add_subplot(2, 4, j+1, projection=ccrs.PlateCarree()))
        axs[j].set_extent(utils.IMG_EXTENT)
        axs[j].coastlines(resolution='10m', color='black', linewidth=1)

    images = []
    stds = []

    im = axs[0].imshow(all_stats_df[param + "_ddpm_mean"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[0].label_outer()
    im = axs[1].imshow(all_stats_df[param + "_ddpm_std"].mean(), cmap="plasma", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    stds.append(im)
    axs[1].label_outer()
    im = axs[2].imshow(all_stats_df[param + "_ddpm_Q5"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[2].label_outer()
    im = axs[3].imshow(all_stats_df[param + "_ddpm_Q95"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[3].label_outer()    

    im = axs[4].imshow(all_stats_df[param + "_arome_mean"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[4].label_outer()
    im = axs[5].imshow(all_stats_df[param + "_arome_std"].mean(), cmap="plasma", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    stds.append(im)
    axs[1].label_outer()
    im = axs[6].imshow(all_stats_df[param + "_arome_Q5"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[6].label_outer()
    im = axs[7].imshow(all_stats_df[param + "_arome_Q95"].mean(), cmap="viridis", origin='upper', 
                        extent=utils.IMG_EXTENT, transform=ccrs.PlateCarree())
    images.append(im)
    axs[7].label_outer()        
    
    # same scale for all mean, Q5, Q95 images
    vmin = min(image.get_array().min() for image in images)
    vmax = max(image.get_array().max() for image in images)
    norm = colors.Normalize(vmin=vmin, vmax=vmax)
    for im in images:
        im.set_norm(norm)

    # another scale for std images
    vmin = min(std.get_array().min() for std in stds)
    vmax = max(std.get_array().max() for std in stds)
    norm = colors.Normalize(vmin=vmin, vmax=vmax)
    for std in stds:
        std.set_norm(norm)

    fig.colorbar(images[0], ax=axs[0])
    fig.colorbar(images[0], ax=axs[2])
    fig.colorbar(images[0], ax=axs[3])
    fig.colorbar(images[0], ax=axs[4])
    fig.colorbar(images[0], ax=axs[6])
    fig.colorbar(images[0], ax=axs[7])
    fig.colorbar(stds[0], ax=axs[1])
    fig.colorbar(stds[0], ax=axs[5])

    axs[0].set_title("mean DDPM")
    axs[1].set_title("std DDPM")
    axs[2].set_title("Q5 DDPM")
    axs[3].set_title("Q95 DDPM")
    axs[4].set_title("mean Arome")
    axs[5].set_title("std Arome")
    axs[6].set_title("Q5 Arome")
    axs[7].set_title("Q95 Arome")

    plt.savefig(output_dir + 'all_stats_synthesis_unique_' + param + '.png', bbox_inches='tight')


def synthesis_stat_distrib(mean_df, std_df, Q5_df, Q95_df, output_dir, param):
    
    D = np.zeros((len(mean_df), 6))
    for i in range(len(mean_df)):
        D[i, 0] = mean_df[param + "_ddpm"].iloc[i].mean()
        D[i, 1] = Q5_df[param + "_ddpm"].iloc[i].mean()
        D[i, 2] = Q95_df[param + "_ddpm"].iloc[i].mean()
        D[i, 3] = mean_df[param + "_arome"].iloc[i].mean()
        D[i, 4] = Q5_df[param + "_arome"].iloc[i].mean()
        D[i, 5] = Q95_df[param + "_arome"].iloc[i].mean()
    labels = ['mean DDPM', 'Q5 DDPM', 'Q95 DDPM', 'mean Arome', 'Q5 Arome', 'Q95 Arome']

    D_std = np.zeros((len(mean_df), 2))
    for i in range(len(mean_df)):
        D_std[i, 0] = std_df[param + "_ddpm"].iloc[i].mean()
        D_std[i, 1] = std_df[param + "_arome"].iloc[i].mean()
    labels_std = ['std DDPM', 'std Arome']

    
    fig, axs = plt.subplots(nrows=1, ncols=2, figsize=(20, 10))
    axs[0].grid()
    VP = axs[0].boxplot(D, positions=[3, 6, 9, 12, 15, 18], widths=1.5, patch_artist=True,
                    showmeans=True, meanline=True, showfliers=False,
                    medianprops={"color": "white", "linewidth": 0.5},
                    boxprops={"facecolor": "C0", "edgecolor": "white",
                            "linewidth": 0.5},
                    whiskerprops={"color": "C0", "linewidth": 1.5},
                    capprops={"color": "C0", "linewidth": 1.5},
                    meanprops = dict(linestyle='--', linewidth=2.5, color='purple'),
                    labels=labels)
    axs[0].tick_params(axis='x', rotation=45)

    axs[1].grid()
    VP = axs[1].boxplot(D_std, positions=[3, 6], widths=0.5, patch_artist=True,
                    showmeans=True, meanline=True, showfliers=False,
                    medianprops={"color": "white", "linewidth": 0.5},
                    boxprops={"facecolor": "C0", "edgecolor": "white",
                            "linewidth": 0.5},
                    whiskerprops={"color": "C0", "linewidth": 1.5},
                    capprops={"color": "C0", "linewidth": 1.5},
                    meanprops = dict(linestyle='--', linewidth=2.5, color='purple'),
                    labels=labels_std)
    axs[1].tick_params(axis='x', rotation=45)

    plt.savefig(output_dir + 'synthesis_distributions.png')
  


if __name__ == "__main__":
    from bronx.stdtypes.date import daterangex as rangex
    from data.load_data import delete_missing_days

    working_dir = "/cnrm/recyf/Data/users/danjoul/ddpm_ensemble/50_members/"
    params = ["u10", "v10"]
    param = "u10"
    dates_arome = rangex([
        "2022030218-2022030218-PT24H",
        "2022030318-2022030318-PT24H",
        "2022030818-2022030818-PT24H",
        "2022031818-2022031818-PT24H",
        "2022031018-2022031018-PT24H",
        "2022032218-2022032218-PT24H",
        "2022032518-2022032518-PT24H",
        "2022032618-2022032618-PT24H",
        "2022043018-2022043018-PT24H",
        "2022050218-2022050218-PT24H",
        "2022050418-2022050418-PT24H",
        "2022050918-2022050918-PT24H",
        "2022051018-2022051018-PT24H",
        "2022052218-2022052218-PT24H",
        "2022052418-2022052418-PT24H"
    ])
    echeances_arome = [12, 27, 42]

    ddpm = load_ensemble(
        working_dir,
        n_members=50,
        params=params
    )

    print(len(ddpm.columns))

    arome = load_ensemble_arome(
        dates=dates_arome,
        echeances=echeances_arome,
        params=params,
        n_members=17,
        data_location="/cnrm/recyf/Data/users/danjoul/dataset/ensemble/"
    )
    arome = correct_dates_for_arome(arome)

    mean_arome = compute_pointwise_mean(arome, 17, params)
    std_arome  = compute_pointwise_std(arome, 17, params)
    Q5_arome   = compute_pointwise_Q5(arome, 17, params)
    Q95_arome  = compute_pointwise_Q95(arome, 17, params)
    mean_ddpm  = compute_pointwise_mean(ddpm , 50 , params)
    std_ddpm   = compute_pointwise_std(ddpm , 50 , params)
    Q5_ddpm    = compute_pointwise_Q5(ddpm , 50 , params)
    Q95_ddpm   = compute_pointwise_Q95(ddpm , 50 , params)

    mean = group_ensembles(mean_arome, mean_ddpm) 
    std  = group_ensembles(std_arome, std_ddpm) 
    Q95  = group_ensembles(Q5_arome, Q5_ddpm)
    Q5   = group_ensembles(Q95_arome, Q95_ddpm)

    synthesis_unique_all_stats_ensemble(
        mean,
        std,
        Q5,
        Q95,
        working_dir,
        param
    )

    synthesis_stat_distrib(mean, std, Q5, Q95, working_dir, param)
    synthesis_unique_all_stats_ensemble(
        mean,
        std,
        Q5,
        Q95,
        working_dir,
        param
    )

    