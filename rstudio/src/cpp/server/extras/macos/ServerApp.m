/*
 * Copyright (C) 2026 by Posit Software, PBC
 * Licensed under the GNU Affero General Public License, version 3.
 */

#import <Cocoa/Cocoa.h>
#import <ServiceManagement/ServiceManagement.h>
#import "ServerAdmin.h"
#include <stdio.h>
#include <string.h>

static SMAppService *serverService(void)
{
   return [SMAppService daemonServiceWithPlistName:@"com.rstudio.launchd.rserver.plist"];
}

static BOOL enableService(NSError **error)
{
   NSString *serverPath = [NSBundle.mainBundle.bundlePath
      stringByAppendingPathComponent:@"Contents/Resources/app/bin/rserver"];
   if (![NSFileManager.defaultManager isExecutableFileAtPath:serverPath])
   {
      if (error)
         *error = [NSError errorWithDomain:@"org.rstudio.RStudioServer" code:1
            userInfo:@{NSLocalizedDescriptionKey:
               @"The Server files are missing. Install the complete RStudioServer.app before enabling startup."}];
      return NO;
   }
   if (![NSFileManager.defaultManager fileExistsAtPath:@"/etc/pam.d/rstudio"])
   {
      if (error)
         *error = [NSError errorWithDomain:@"org.rstudio.RStudioServer" code:2
            userInfo:@{NSLocalizedDescriptionKey:
               @"Server authentication is not configured. Complete the administrator installation before enabling startup."}];
      return NO;
   }
   SMAppService *service = serverService();
   if (service.status == SMAppServiceStatusEnabled ||
       service.status == SMAppServiceStatusRequiresApproval)
      return YES;
   return [service registerAndReturnError:error];
}

static BOOL disableService(NSError **error)
{
   SMAppService *service = serverService();
   if (service.status == SMAppServiceStatusNotRegistered)
      return YES;
   return [service unregisterAndReturnError:error];
}

@interface ServerAppDelegate : NSObject <NSApplicationDelegate>
@property(strong) NSWindow *window;
@property(strong) NSTextField *statusLabel;
@property(strong) ServerSettingsController *settingsController;
@property(strong) ServerAccountsController *accountsController;
@end

@implementation ServerAppDelegate

- (void)refreshStatus
{
   switch (serverService().status)
   {
   case SMAppServiceStatusEnabled:
      self.statusLabel.stringValue = @"Startup enabled. macOS manages the Server in the background.";
      break;
   case SMAppServiceStatusRequiresApproval:
      self.statusLabel.stringValue = @"Administrator approval is required in System Settings > Login Items.";
      break;
   case SMAppServiceStatusNotFound:
      self.statusLabel.stringValue = @"The Server service could not be found in this application.";
      break;
   default:
      self.statusLabel.stringValue = @"Automatic startup is disabled.";
      break;
   }
}

- (void)showError:(NSError *)error
{
   NSAlert *alert = [NSAlert new];
   alert.messageText = @"RStudio Server could not update automatic startup";
   alert.informativeText = error.localizedDescription ?: @"Check the application installation and try again.";
   [alert runModal];
}

- (void)enableStartup:(id)sender
{
   NSError *error = nil;
   BOOL enabled = enableService(&error);
   [self refreshStatus];
   if (serverService().status == SMAppServiceStatusRequiresApproval)
   {
      NSAlert *alert = [NSAlert new];
      alert.messageText = @"Allow RStudio Server to start in the background";
      alert.informativeText = @"Open System Settings > Login Items and allow RStudio Server under background items. macOS requires administrator approval before the Server can start, including at boot.";
      [alert addButtonWithTitle:@"Open System Settings"];
      [alert addButtonWithTitle:@"Later"];
      if ([alert runModal] == NSAlertFirstButtonReturn)
         [SMAppService openSystemSettingsLoginItems];
   }
   else if (!enabled)
      [self showError:error];
}

- (void)disableStartup:(id)sender
{
   NSError *error = nil;
   if (!disableService(&error))
      [self showError:error];
   [self refreshStatus];
}

- (void)openSettings:(id)sender
{
   [SMAppService openSystemSettingsLoginItems];
}

- (void)showServerSettings:(id)sender
{
   // Recreate the settings editor to reload the authoritative on-disk config.
   [self.settingsController close];
   self.settingsController = [ServerSettingsController new];
   [self.settingsController showWindow:nil];
}

- (void)showAccounts:(id)sender
{
   if (!self.accountsController) self.accountsController = [ServerAccountsController new];
   [self.accountsController showWindow:nil];
}

- (void)showInstallationHelp:(id)sender
{
   NSURL *guide = [NSURL fileURLWithPath:[NSBundle.mainBundle.bundlePath
      stringByAppendingPathComponent:@"Contents/Resources/app/SERVER.md"]];
   [NSWorkspace.sharedWorkspace openURL:guide];
}

- (void)applicationDidBecomeActive:(NSNotification *)notification
{
   [self refreshStatus];
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification
{
   self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 660, 300)
      styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
      backing:NSBackingStoreBuffered defer:NO];
   self.window.title = @"RStudio Server";
   NSTextField *description = [NSTextField wrappingLabelWithString:
      @"Run RStudio Server as a background service, including before a Mac user signs in. Enable startup, then approve RStudio Server in macOS Login Items settings."];
   description.frame = NSMakeRect(24, 210, 612, 65);
   [self.window.contentView addSubview:description];
   self.statusLabel = [NSTextField wrappingLabelWithString:@""];
   self.statusLabel.frame = NSMakeRect(24, 145, 612, 55);
   [self.window.contentView addSubview:self.statusLabel];
   NSArray *titles = @[@"Enable Startup", @"Stop and Disable Startup", @"Open Login Items",
                       @"Server Settings…", @"User Accounts…", @"Installation Help…"];
   SEL actions[] = {@selector(enableStartup:), @selector(disableStartup:), @selector(openSettings:)};
   SEL helpActions[] = {@selector(showServerSettings:), @selector(showAccounts:), @selector(showInstallationHelp:)};
   for (NSUInteger i = 0; i < titles.count; ++i)
   {
      NSButton *button = [NSButton buttonWithTitle:titles[i] target:self action:(i < 3 ? actions[i] : helpActions[i - 3])];
      button.frame = NSMakeRect(16 + (i % 3) * 212, i < 3 ? 88 : 32, 208, 34);
      [self.window.contentView addSubview:button];
   }
   [self refreshStatus];
   [self.window center];
   [self.window makeKeyAndOrderFront:nil];
   [NSApp activateIgnoringOtherApps:YES];
   if (serverService().status == SMAppServiceStatusNotRegistered)
   {
      NSAlert *alert = [NSAlert new];
      alert.messageText = @"Start RStudio Server automatically?";
      alert.informativeText = @"macOS will ask an administrator to approve background startup in System Settings. You can change this later.";
      [alert addButtonWithTitle:@"Enable Startup"];
      [alert addButtonWithTitle:@"Not Now"];
      if ([alert runModal] == NSAlertFirstButtonReturn)
         [self enableStartup:nil];
   }
   else if (serverService().status == SMAppServiceStatusRequiresApproval)
      [self enableStartup:nil];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender
{
   return YES;
}
@end

static void installMenus(ServerAppDelegate *delegate)
{
   NSMenu *menuBar = [NSMenu new];
   NSMenuItem *applicationItem = [NSMenuItem new];
   [menuBar addItem:applicationItem];
   NSMenu *applicationMenu = [[NSMenu alloc] initWithTitle:@"RStudio Server"];
   [applicationMenu addItemWithTitle:@"About RStudio Server" action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
   NSMenuItem *settings = [applicationMenu addItemWithTitle:@"Server Settings…" action:@selector(showServerSettings:) keyEquivalent:@","];
   settings.target = delegate;
   [applicationMenu addItem:NSMenuItem.separatorItem];
   [applicationMenu addItemWithTitle:@"Quit RStudio Server" action:@selector(terminate:) keyEquivalent:@"q"];
   applicationItem.submenu = applicationMenu;

   NSMenuItem *editItem = [NSMenuItem new];
   NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Edit"];
   [editMenu addItemWithTitle:@"Undo" action:@selector(undo:) keyEquivalent:@"z"];
   [editMenu addItem:NSMenuItem.separatorItem];
   [editMenu addItemWithTitle:@"Cut" action:@selector(cut:) keyEquivalent:@"x"];
   [editMenu addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
   [editMenu addItemWithTitle:@"Paste" action:@selector(paste:) keyEquivalent:@"v"];
   [editMenu addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
   editItem.submenu = editMenu;
   [menuBar addItem:editItem];

   NSMenuItem *helpItem = [NSMenuItem new];
   NSMenu *helpMenu = [[NSMenu alloc] initWithTitle:@"Help"];
   NSMenuItem *accounts = [helpMenu addItemWithTitle:@"User Accounts…" action:@selector(showAccounts:) keyEquivalent:@""];
   accounts.target = delegate;
   NSMenuItem *installation = [helpMenu addItemWithTitle:@"Installation and Removal" action:@selector(showInstallationHelp:) keyEquivalent:@""];
   installation.target = delegate;
   helpItem.submenu = helpMenu;
   [menuBar addItem:helpItem];
   NSApp.mainMenu = menuBar;
   NSApp.helpMenu = helpMenu;
}

int main(int argc, const char *argv[])
{
   @autoreleasepool
   {
      if (argc == 4 && strcmp(argv[1], "--validate-network") == 0)
      {
         NSString *error = RStudioValidateNetwork([NSString stringWithUTF8String:argv[2]], [NSString stringWithUTF8String:argv[3]]);
         if (error) fprintf(stderr, "%s\n", error.UTF8String);
         return error ? 1 : 0;
      }
      if (argc == 2)
      {
         if (strcmp(argv[1], "--service-status") == 0)
         {
            switch (serverService().status)
            {
            case SMAppServiceStatusEnabled: puts("enabled"); break;
            case SMAppServiceStatusRequiresApproval: puts("approval-required"); break;
            case SMAppServiceStatusNotFound: puts("not-found"); break;
            default: puts("disabled"); break;
            }
            return 0;
         }
         NSError *error = nil;
         BOOL success = NO;
         if (strcmp(argv[1], "--enable-service") == 0)
         {
            success = enableService(&error);
            if (serverService().status == SMAppServiceStatusRequiresApproval)
            {
               fprintf(stderr, "Approve RStudio Server in System Settings > Login Items. Open RStudioServer.app for the settings shortcut.\n");
               return 3;
            }
         }
         else if (strcmp(argv[1], "--disable-service") == 0)
            success = disableService(&error);
         else
         {
            fprintf(stderr, "Usage: RStudioServer [--enable-service|--disable-service|--service-status|--validate-network ADDRESS PORT]\n");
            return 2;
         }
         if (!success)
            fprintf(stderr, "%s\n", error.localizedDescription.UTF8String);
         return success ? 0 : 1;
      }
      NSApplication *app = [NSApplication sharedApplication];
      app.activationPolicy = NSApplicationActivationPolicyRegular;
      ServerAppDelegate *delegate = [ServerAppDelegate new];
      app.delegate = delegate;
      installMenus(delegate);
      [app run];
   }
   return 0;
}
