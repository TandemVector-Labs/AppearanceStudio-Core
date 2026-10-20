from __future__ import annotations
import json, threading
import gi
gi.require_version("Gtk","4.0")
gi.require_version("Adw","1")
from gi.repository import Gtk, Adw, GLib
from .engine import all_themes, apply, status
from .paths import pack_roots
from .registry import discover
from .diagnostics import report as diagnostic_report

APP_ID="io.appearancestudio.Studio"
APP_NAME="Appearance Studio"

class StudioWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app,title=APP_NAME)
        self.set_default_size(980,720)
        self.set_size_request(680,520)
        self._busy=False

        self.toast=Adw.ToastOverlay()
        self.toolbar=Adw.ToolbarView()
        self.header=Adw.HeaderBar()
        self.title=Adw.WindowTitle.new(APP_NAME,"Professional desktop appearance center")
        self.header.set_title_widget(self.title)
        self.toolbar.add_top_bar(self.header)

        self.stack=Adw.ViewStack()
        self.stack.set_vexpand(True)
        self.stack.add_titled_with_icon(self._themes_page(),"themes","Themes","applications-graphics-symbolic")
        self.stack.add_titled_with_icon(self._packs_page(),"packs","Packs","package-x-generic-symbolic")
        self.stack.add_titled_with_icon(self._diagnostics_page(),"diagnostics","Diagnostics","utilities-system-monitor-symbolic")
        self.stack.add_titled_with_icon(self._about_page(),"about","About","help-about-symbolic")
        self.toolbar.set_content(self.stack)

        switcher=Adw.ViewSwitcherBar()
        switcher.set_stack(self.stack)
        switcher.set_reveal(True)
        self.toolbar.add_bottom_bar(switcher)
        self.toast.set_child(self.toolbar)
        self.set_content(self.toast)

    def _page(self):
        page=Adw.PreferencesPage()
        page.set_margin_top(12);page.set_margin_bottom(12)
        page.set_margin_start(12);page.set_margin_end(12)
        return page

    def _themes_page(self):
        page=self._page()
        overview=Adw.PreferencesGroup(title="Theme library",description="Apply a complete theme identity with bounded, transactional desktop settings.")
        page.add(overview)
        try:
            current=status()["current"]
            current_row=Adw.ActionRow(title="Current desktop")
            current_row.set_subtitle(f"GTK {current['gtk']} · Icons {current['icons']} · Cursor {current['cursor']}")
            overview.add(current_row)
        except Exception as exc:
            row=Adw.ActionRow(title="Current desktop",subtitle="Status is temporarily unavailable.")
            overview.add(row)

        for theme_id,theme in all_themes().items():
            row=Adw.ActionRow(title=theme.name,subtitle=f"{theme.pack_id} · {theme.dark_theme} / {theme.light_theme}")
            box=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=6,valign=Gtk.Align.CENTER)
            dark=Gtk.Button(label="Dark")
            light=Gtk.Button(label="Light")
            dark.connect("clicked",lambda _b,t=theme_id:self._apply_async(t,"dark"))
            light.connect("clicked",lambda _b,t=theme_id:self._apply_async(t,"light"))
            box.append(light);box.append(dark)
            row.add_suffix(box)
            overview.add(row)
        return page

    def _packs_page(self):
        page=self._page()
        group=Adw.PreferencesGroup(title="Installed theme packs",description="Theme packs are isolated, hash-verified and loaded from user or application data directories.")
        page.add(group)
        try:
            packs=discover(pack_roots())
            for pack in packs:
                state="Public distribution approved" if pack.public_distribution_approved else "Local / release-candidate content"
                row=Adw.ActionRow(title=pack.name,subtitle=f"Version {pack.version} · {pack.license} · {state}")
                badge=Gtk.Label(label=str(len(pack.themes))+" theme" + ("" if len(pack.themes)==1 else "s"))
                badge.add_css_class("dim-label")
                row.add_suffix(badge)
                group.add(row)
        except Exception:
            group.add(Adw.ActionRow(title="Pack status unavailable",subtitle="Run Diagnostics for details."))
        return page

    def _diagnostics_page(self):
        page=self._page()
        group=Adw.PreferencesGroup(title="Health & compatibility",description="Read-only checks for the application, theme packs and desktop dependencies.")
        page.add(group)
        self.diag_summary=Adw.ActionRow(title="Diagnostics",subtitle="Not run yet")
        group.add(self.diag_summary)
        button=Gtk.Button(label="Run Diagnostics",halign=Gtk.Align.START)
        button.connect("clicked",self._run_diagnostics)
        group.add(button)
        return page

    def _about_page(self):
        page=self._page()
        product=Adw.PreferencesGroup(title=APP_NAME,description="A professional appearance center for GNOME desktops.")
        page.add(product)
        product.add(Adw.ActionRow(title="Version",subtitle="0.9.0"))
        product.add(Adw.ActionRow(title="Publisher",subtitle="TandemVector-Labs"))
        product.add(Adw.ActionRow(title="Author",subtitle="Aliakbar Emadoddin · علی‌اکبر عمادالدین"))
        product.add(Adw.ActionRow(title="Design",subtitle="Portable core · verified theme packs · bounded desktop writes · transactional rollback"))
        privacy=Adw.PreferencesGroup(title="Privacy",description="Appearance Studio manages local desktop settings. The public product contains no developer-machine identity or private project metadata.")
        page.add(privacy)
        privacy.add(Adw.ActionRow(title="Third-party components",subtitle="Required upstream licenses and attribution are preserved in the LICENSES directory."))
        return page

    def _apply_async(self,theme,mode):
        if self._busy:
            self.toast.add_toast(Adw.Toast.new("Another appearance operation is already running."))
            return
        self._busy=True
        self.title.set_subtitle(f"Applying {theme} · {mode}")
        def work():
            try:
                result=apply(theme,mode)
                GLib.idle_add(self._finish_apply,True,result)
            except Exception as exc:
                GLib.idle_add(self._finish_apply,False,str(exc))
        threading.Thread(target=work,daemon=True,name="appearance-apply").start()

    def _finish_apply(self,ok,payload):
        self._busy=False
        self.title.set_subtitle("Professional desktop appearance center")
        if ok:
            writes=payload.get("write_count",0)
            self.toast.add_toast(Adw.Toast.new(f"Theme applied · {writes} changed setting" + ("" if writes==1 else "s")))
        else:
            self.toast.add_toast(Adw.Toast.new("Apply failed safely; previous appearance was restored."))
        return GLib.SOURCE_REMOVE

    def _run_diagnostics(self,_button):
        self.diag_summary.set_subtitle("Running read-only checks…")
        def work():
            try:
                data=diagnostic_report()
                GLib.idle_add(self._finish_diagnostics,data)
            except Exception as exc:
                GLib.idle_add(self._finish_diagnostics,{"pass":False,"errors":[str(exc)]})
        threading.Thread(target=work,daemon=True,name="appearance-diagnostics").start()

    def _finish_diagnostics(self,data):
        checks=data.get("checks",{})
        passed=sum(1 for v in checks.values() if v)
        total=len(checks)
        warnings=len(data.get("warnings",[]))
        self.diag_summary.set_subtitle(f"{passed}/{total} checks passed · {warnings} warning" + ("" if warnings==1 else "s"))
        self.toast.add_toast(Adw.Toast.new("Diagnostics passed." if data.get("pass") else "Diagnostics found an issue."))
        return GLib.SOURCE_REMOVE

class StudioApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
    def do_activate(self):
        window=self.props.active_window
        if not window:
            window=StudioWindow(self)
        window.present()

def main():
    return StudioApplication().run(None)
