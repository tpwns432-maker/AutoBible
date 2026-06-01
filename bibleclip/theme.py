"""Light / Dark color palettes."""

LIGHT_THEME = {
    'bg': '#F6F5FB', 'fg': '#23202E',
    'viewer_bg': '#FFFFFF', 'viewer_fg': '#262333',
    'highlight_bg': '#FFE39A', 'highlight_fg': '#2A2010',
    'select_bg': '#6D4DFF', 'select_fg': '#FFFFFF',
    'scroll_thumb': '#CAC4DD', 'scroll_trough': '#ECE9F4', 'scroll_active': '#A79FC4',
    'lex_hl_bg': '#EBE4FF',
    'accent': '#6D4DFF', 'accent_hover': '#5A3FE0',
    'button_bg': '#F0ECFA', 'button_fg': '#5A3FD0', 'button_active': '#E2DAF6',
    'frame_bg': '#F0EEF7',
    'entry_bg': '#FFFFFF', 'entry_fg': '#262333',
    'border': '#E4DEF2', 'verse_num': '#6D4DFF',
    'status_bg': '#E7F6EC', 'status_fg': '#2E8B57',
    'status_off_bg': '#FCEAEE', 'status_off_fg': '#C0395A',
    'separator': '#E4DEF2',
    'listbox_bg': '#FFFFFF', 'listbox_fg': '#262333',
    'listbox_sel_bg': '#EBE4FF', 'listbox_sel_fg': '#3A2E78',
    'preview_bg': '#F4F1FD', 'preview_fg': '#262333',
    'radio_bg': '#F0EEF7', 'radio_fg': '#23202E', 'radio_sel': '#FFFFFF',
}

DARK_THEME = {
    'bg': '#16131F', 'fg': '#E8E5F2',
    'viewer_bg': '#1C1828', 'viewer_fg': '#E6E3F0',
    'highlight_bg': '#F4D58D', 'highlight_fg': '#1A1330',
    'select_bg': '#4C3AA8', 'select_fg': '#FFFFFF',
    'scroll_thumb': '#4A4366', 'scroll_trough': '#141019', 'scroll_active': '#6B6294',
    'lex_hl_bg': '#39325A',
    'accent': '#9A86FF', 'accent_hover': '#B3A4FF',
    'button_bg': '#251F38', 'button_fg': '#C9C0EC', 'button_active': '#322A4E',
    'frame_bg': '#1A1626',
    'entry_bg': '#221C34', 'entry_fg': '#E6E3F0',
    'border': '#2C2542', 'verse_num': '#9A86FF',
    'status_bg': '#1C2A20', 'status_fg': '#7EE0A1',
    'status_off_bg': '#2E1F28', 'status_off_fg': '#F2899F',
    'separator': '#2C2542',
    'listbox_bg': '#221C34', 'listbox_fg': '#E6E3F0',
    'listbox_sel_bg': '#39325A', 'listbox_sel_fg': '#FFFFFF',
    'preview_bg': '#141019', 'preview_fg': '#E6E3F0',
    'radio_bg': '#16131F', 'radio_fg': '#E8E5F2', 'radio_sel': '#221C34',
}


# CustomTkinter palette (Medium redesign). Each value is a (light, dark) tuple
# so CTk widgets auto-switch with the appearance mode. Violet/indigo "pipeline"
# palette: accent #6D4DFF (light) / #9A86FF (dark).
CTK = {
    'accent':        ('#6D4DFF', '#9A86FF'),
    'accent_hover':  ('#5A3FE0', '#B3A4FF'),
    'on_accent':     ('#FFFFFF', '#FFFFFF'),
    'app_bg':        ('#F6F5FB', '#16131F'),
    'card':          ('#FFFFFF', '#1C1828'),
    'card_border':   ('#E7E4F2', '#2C2542'),
    'text':          ('#1C1B2E', '#E8E5F2'),
    'muted':         ('#6B6880', '#A99FC6'),
    'btn':           ('#F0ECFA', '#251F38'),
    'btn_hover':     ('#E2DAF6', '#322A4E'),
    'btn_text':      ('#5A3FD0', '#C9C0EC'),
    'status_on_bg':  ('#E7F6EC', '#1C2A20'),
    'status_on_fg':  ('#2E8B57', '#7EE0A1'),
    'status_off_bg': ('#FCEAEE', '#2E1F28'),
    'status_off_fg': ('#C0395A', '#F2899F'),
}
