"""Measured per-channel DMA eye margins; never infer unmeasured taps as passes."""


def point_rates(point):
    """Worst error fraction per lane, using each check's own denominator."""
    transitions = int(point.transitionsPerChannel)
    boundaries = int(point.boundary_transitions_per_channel)
    samples = transitions + boundaries + 1  # N*(L-1) + (N-1) + 1 = N*L
    if transitions <= 0 or any(len(v) != 8 for v in
            (point.channelFailures, point.low_bit_failures, point.boundary_failures)):
        raise ValueError('DMA eye point requires transition counts and eight lanes')
    if not boundaries and any(point.boundary_failures):
        raise ValueError('DMA eye point has boundary errors without boundary observations')
    return [max(point.channelFailures[lane] / transitions,
                point.low_bit_failures[lane] / samples,
                point.boundary_failures[lane] / boundaries if boundaries else 0)
            for lane in range(8)]


def measured_margins(afe_result):
    points = sorted((p for p in afe_result.points if p.bitslip == afe_result.bitslip),
                    key=lambda p: p.tap)
    taps = [p.tap for p in points]
    if len(set(taps)) != len(taps):
        raise ValueError('Duplicate DMA eye points at selected bitslip')
    rates = [point_rates(p) for p in points]
    metrics = []
    for lane in range(8):
        index = taps.index(afe_result.selected_delay) if afe_result.selected_delay in taps else None
        metric = {'channel': afe_result.afe * 8 + lane, 'window_at_selected': None,
                  'sampled_span_taps': None, 'sampled_margin_taps': None,
                  'tested_points': 0, 'coverage_clipped': [], 'marginal': False,
                  'approved': bool(afe_result.approved_lane_mask & (1 << lane))}
        if afe_result.approved_lane_mask and index is not None and rates[index][lane] == 0:
            first = last = index
            while first > 0 and rates[first - 1][lane] == 0:
                first -= 1
            while last + 1 < len(points) and rates[last + 1][lane] == 0:
                last += 1
            margin = min(taps[index] - taps[first], taps[last] - taps[index])
            spacings = [b - a for a, b in zip(taps, taps[1:])]
            resolution = max(spacings) if spacings else 1
            metric.update(window_at_selected=[taps[first], taps[last]],
                          sampled_span_taps=taps[last] - taps[first],
                          sampled_margin_taps=margin, tested_points=last - first + 1,
                          coverage_clipped=(['left'] if first == 0 else []) +
                                           (['right'] if last == len(points) - 1 else []),
                          marginal=margin <= resolution)
        metrics.append(metric)
    return points, rates, metrics


def save_channel_eye(directory, afe_result):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch, Rectangle
    import numpy as np

    a = afe_result
    points, rates, metrics = measured_margins(a)
    if not points:
        return metrics
    values = np.full((8, 512), np.nan)
    for p, row in zip(points, rates):
        for lane, rate in enumerate(row):
            if rate:
                values[lane, p.tap] = rate
    positive = values[np.isfinite(values)]
    minimum = min(float(positive.min()), .1) if positive.size else 1e-6
    fig, (errors, windows) = plt.subplots(2, 1, figsize=(13, 9), sharex=True,
                                         gridspec_kw={'height_ratios': [1.1, 1]})
    fig.subplots_adjust(left=.08, right=.76, top=.86, bottom=.20, hspace=.42)
    colors = plt.get_cmap('magma_r').copy()
    colors.set_bad('#e5e7eb')
    img = errors.imshow(values, origin='lower', aspect='auto', interpolation='nearest',
                        extent=(-.5, 511.5, -.5, 7.5), cmap=colors,
                        norm=LogNorm(vmin=minimum, vmax=1))
    for p, row in zip(points, rates):
        for lane, rate in enumerate(row):
            if not rate:
                errors.add_patch(Rectangle((p.tap - .5, lane - .5), 1, 1,
                                           facecolor='#15803d', edgecolor='none'))
    cax = fig.add_axes([.80, .57, .015, .26])
    fig.colorbar(img, cax=cax, label='Worst error fraction (log scale)')
    errors.set_title('Errors by channel at selected BITSLIP', loc='left')
    errors.tick_params(labelbottom=True)
    errors.set_xlabel('IDELAY tap')
    fig.legend(handles=[Patch(color='#15803d', label='Zero observed errors'),
                        Patch(color='#e5e7eb', label='Not measured')],
               loc='upper left', bbox_to_anchor=(.08, .94), ncol=2, fontsize=9)
    for lane, metric in enumerate(metrics):
        passing = [p.tap for p, row in zip(points, rates) if row[lane] == 0]
        failing = [p.tap for p, row in zip(points, rates) if row[lane] != 0]
        windows.scatter(failing, [lane] * len(failing), color='#b91c1c', s=15, marker='x')
        windows.scatter(passing, [lane] * len(passing), color='#15803d', s=18)
        window = metric['window_at_selected']
        if window:
            color = '#d97706' if metric['marginal'] else '#15803d'
            windows.plot(window, [lane, lane], color=color, lw=4, alpha=.65)
            windows.scatter([a.selected_delay], [lane], color=color, edgecolor='black',
                            marker='D', s=40, zorder=5)
            note = f"{metric['sampled_span_taps']:3d} / {metric['sampled_margin_taps']:3d}"
            if metric['coverage_clipped']:
                note += ' *'
            if metric['marginal']:
                note += '  narrow'
        else:
            note = 'no pass at selected tap' if a.approved_lane_mask else 'no approved tap'
        if a.approved_lane_mask and not metric['approved']:
            note += ' (excluded)'
        windows.text(1.035, lane, note, transform=windows.get_yaxis_transform(),
                     fontsize=9, va='center', family='monospace')
    windows.text(1.035, 8.0, 'Span / margin (taps)',
                 transform=windows.get_yaxis_transform(), fontsize=10, weight='bold')
    windows.set_title('Passing run containing selected tap; measured points only', loc='left')
    windows.set_xlabel('IDELAY tap')
    fig.legend(handles=[Line2D([], [], color='#15803d', marker='o', ls='', label='Pass'),
                        Line2D([], [], color='#b91c1c', marker='x', ls='', label='Fail'),
                        Line2D([], [], color='#d97706', lw=4, label='Margin <= one scan step'),
                        Patch(color='#06b6d4', alpha=.2, label='Common/subset eye')],
               loc='upper left', bbox_to_anchor=(.08, .13), ncol=4, fontsize=9)
    for ax in (errors, windows):
        ax.set_yticks(range(8), [f'ch{a.afe * 8 + lane:02d}' for lane in range(8)])
        ax.set_ylim(-.6, 7.6)
        ax.set_xlim(max(-.5, points[0].tap - 4), min(511.5, points[-1].tap + 4))
        if a.approved_lane_mask:
            ax.axvline(a.selected_delay, color='black', ls='--', lw=1)
    if a.approved_lane_mask:
        windows.axvspan(a.first_passing_tap, a.last_passing_tap, color='#06b6d4', alpha=.12)
    state = 'APPLIED' if a.applied else 'NOT APPLIED'
    state += f' ({int(a.approved_lane_mask).bit_count()}/8 channels approved)'
    selected = f'tap {a.selected_delay}' if a.approved_lane_mask else 'no approved tap'
    fig.suptitle(f'AFE{a.afe} / DMA  |  BITSLIP {a.bitslip}  |  {selected}  |  {state}',
                 fontsize=15, y=.98)
    fig.text(.08, .025, 'Span = last - first sampled passing tap; margin = distance to nearer sampled run edge.\n'
                       '* Run reaches scan coverage edge: its full width is unknown. Unmeasured taps are not qualified.\n'
                       'Short-scan zero errors are a candidate; application requires the server final verification.',
             fontsize=9, va='bottom')
    fig.savefig(directory / f'afe{a.afe}_delay_eye.png', dpi=160)
    plt.close(fig)
    return metrics


def save_bitslip_overview(directory, afe_result):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    a = afe_result
    values = np.full((16, 512), np.nan)
    for point in a.points:
        values[point.bitslip, point.tap] = sum(rate == 0 for rate in point_rates(point))
    colors = plt.get_cmap('viridis').copy()
    colors.set_bad('#e5e7eb')
    fig, ax = plt.subplots(figsize=(12, 5))
    img = ax.imshow(values, origin='lower', aspect='auto', interpolation='nearest',
                    extent=(-.5, 511.5, -.5, 15.5), vmin=0, vmax=8, cmap=colors)
    ax.set(xlabel='IDELAY tap', ylabel='BITSLIP',
           title=f'AFE{a.afe}: passing channel count; gray = not measured')
    ax.set_yticks(range(16))
    if a.approved_lane_mask:
        ax.plot(a.selected_delay, a.bitslip, 'rx', markersize=10)
    fig.colorbar(img, ax=ax, label='Channels with zero observed errors')
    fig.tight_layout()
    fig.savefig(directory / f'afe_{a.afe}_eye.png', dpi=150)
    plt.close(fig)
