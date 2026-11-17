/* Copyright (C) 2026 by Posit Software, PBC
 * Licensed under the GNU Affero General Public License, version 3. */
#import "ServerAdmin.h"
#import <ServiceManagement/ServiceManagement.h>
#include <arpa/inet.h>

NSString *RStudioValidateNetwork(NSString *address, NSString *port)
{
   struct in_addr v4;
   struct in6_addr v6;
   if (!address.length || (inet_pton(AF_INET, address.UTF8String, &v4) != 1 &&
       inet_pton(AF_INET6, address.UTF8String, &v6) != 1))
      return @"Enter a numeric IPv4 or IPv6 address, such as 127.0.0.1, 0.0.0.0 or ::1.";
   NSCharacterSet *nonDigits = [NSCharacterSet characterSetWithCharactersInString:@"0123456789"].invertedSet;
   if (port.length == 0 || port.length > 5 || [port rangeOfCharacterFromSet:nonDigits].location != NSNotFound ||
       port.integerValue < 1 || port.integerValue > 65535)
      return @"Enter a port between 1 and 65535.";
   return nil;
}

static NSString *adminPath(void)
{
   return [NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"Contents/Resources/app/bin/rstudio-server"];
}

static NSString *shellQuote(NSString *value)
{
   return [NSString stringWithFormat:@"'%@'", [value stringByReplacingOccurrencesOfString:@"'" withString:@"'\\''"]];
}

static NSTextField *label(NSView *view, NSString *text, NSRect frame)
{
   NSTextField *field = [NSTextField wrappingLabelWithString:text];
   field.frame = frame;
   [view addSubview:field];
   return field;
}

static NSButton *button(NSView *view, NSString *text, NSRect frame, id target, SEL action)
{
   NSButton *control = [NSButton buttonWithTitle:text target:target action:action];
   control.frame = frame;
   [view addSubview:control];
   return control;
}

static NSWindow *adminWindow(NSString *title, CGFloat height)
{
   NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 740, height)
      styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
      backing:NSBackingStoreBuffered defer:NO];
   window.title = title;
   [window center];
   return window;
}

static void showAdminError(NSString *message)
{
   NSAlert *alert = [NSAlert new];
   alert.messageText = @"RStudio Server could not complete the request";
   alert.informativeText = message;
   [alert runModal];
}

static NSString *runAdministratorCommand(NSArray<NSString *> *arguments)
{
   NSMutableArray *quoted = [NSMutableArray arrayWithObject:shellQuote(adminPath())];
   for (NSString *argument in arguments)
      [quoted addObject:shellQuote(argument)];
   NSString *command = [quoted componentsJoinedByString:@" "];
   // Quote shell arguments and the AppleScript string independently. The
   // system authorization dialog handles credentials; the app never reads them.
   command = [command stringByReplacingOccurrencesOfString:@"\\" withString:@"\\\\"];
   command = [command stringByReplacingOccurrencesOfString:@"\"" withString:@"\\\""];
   NSAppleScript *script = [[NSAppleScript alloc] initWithSource:
      [NSString stringWithFormat:@"do shell script \"%@\" with administrator privileges", command]];
   NSDictionary *error = nil;
   NSAppleEventDescriptor *result = [script executeAndReturnError:&error];
   if (!result)
   {
      if ([error[NSAppleScriptErrorNumber] integerValue] != -128)
         showAdminError(error[NSAppleScriptErrorMessage] ?: @"Administrator authorization failed.");
      return nil;
   }
   return result.stringValue ?: @"Done.";
}

@interface ServerSettingsController ()
@property(strong) NSTextField *address;
@property(strong) NSTextField *port;
@property(strong) NSTextField *result;
@end

@implementation ServerSettingsController

- (instancetype)init
{
   self = [super initWithWindow:adminWindow(@"RStudio Server Settings", 440)];
   if (!self) return nil;
   NSView *view = self.window.contentView;
   label(view, @"Listen address and service", NSMakeRect(24, 395, 692, 25));
   label(view, @"127.0.0.1 allows this Mac only. 0.0.0.0 listens on all IPv4 interfaces. Select an address assigned to this Mac. Authentication remains required.", NSMakeRect(24, 330, 692, 52));
   label(view, @"Listen address", NSMakeRect(24, 287, 125, 23));
   self.address = [[NSTextField alloc] initWithFrame:NSMakeRect(155, 285, 360, 26)];
   [view addSubview:self.address];
   label(view, @"Port", NSMakeRect(535, 287, 45, 23));
   self.port = [[NSTextField alloc] initWithFrame:NSMakeRect(585, 285, 125, 26)];
   [view addSubview:self.port];
   button(view, @"Reload Saved Settings", NSMakeRect(24, 235, 215, 32), self, @selector(reload:));
   button(view, @"Save and Apply", NSMakeRect(490, 235, 225, 32), self, @selector(save:));
   label(view, @"Settings are saved in /etc/rstudio/rserver.conf. Applying restarts an enabled service; a stopped service uses them on its next start. Administrator authorization is required.", NSMakeRect(24, 168, 692, 55));
   button(view, @"Start / Enable Startup", NSMakeRect(20, 112, 225, 34), self, @selector(start:));
   button(view, @"Stop and Disable Startup", NSMakeRect(255, 112, 225, 34), self, @selector(stop:));
   button(view, @"Restart", NSMakeRect(490, 112, 225, 34), self, @selector(restart:));
   self.result = label(view, @"", NSMakeRect(24, 15, 692, 82));
   [self reload:nil];
   return self;
}

- (void)reload:(id)sender
{
   NSError *error = nil;
   NSString *text = [NSString stringWithContentsOfFile:@"/etc/rstudio/rserver.conf"
      encoding:NSUTF8StringEncoding error:&error];
   if (!text)
   {
      self.result.stringValue = error.localizedDescription ?: @"Complete administrator installation first.";
      self.address.stringValue = @"";
      self.port.stringValue = @"";
      return;
   }
   NSMutableDictionary *options = [NSMutableDictionary new];
   NSCharacterSet *space = NSCharacterSet.whitespaceAndNewlineCharacterSet;
   for (NSString *line in [text componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet])
   {
      NSString *entry = [[line componentsSeparatedByString:@"#"][0] stringByTrimmingCharactersInSet:space];
      NSRange equals = [entry rangeOfString:@"="];
      if (equals.location == NSNotFound) continue;
      NSString *key = [[entry substringToIndex:equals.location] stringByTrimmingCharactersInSet:space];
      NSString *value = [[entry substringFromIndex:equals.location + 1] stringByTrimmingCharactersInSet:space];
      if (value.length >= 2 && [value hasPrefix:@"\""] && [value hasSuffix:@"\""])
         value = [value substringWithRange:NSMakeRange(1, value.length - 2)];
      options[key] = value;
   }
   self.address.stringValue = options[@"www-address"] ?: @"0.0.0.0";
   NSString *defaultPort = [@[@"1", @"true"] containsObject:[options[@"ssl-enabled"] lowercaseString]] ? @"443" : @"8787";
   self.port.stringValue = [options[@"www-port"] length] ? options[@"www-port"] : defaultPort;
   self.result.stringValue = @"Loaded the saved Server configuration. Startup registration and HTTP service health are separate; use the Server URL to check connectivity.";
}

- (void)save:(id)sender
{
   NSString *error = RStudioValidateNetwork(self.address.stringValue, self.port.stringValue);
   if (error) { showAdminError(error); return; }
   NSString *output = runAdministratorCommand(@[@"configure-network", self.address.stringValue, self.port.stringValue]);
   if (output) { [self reload:nil]; self.result.stringValue = output; }
}

- (void)start:(id)sender
{
   [NSApp sendAction:@selector(enableStartup:) to:NSApp.delegate from:sender];
}

- (void)stop:(id)sender
{
   [NSApp sendAction:@selector(disableStartup:) to:NSApp.delegate from:sender];
}

- (void)restart:(id)sender
{
   NSString *output = runAdministratorCommand(@[@"restart"]);
   if (output) self.result.stringValue = @"Restart requested. The service reads the latest saved configuration.";
}
@end

@interface ServerAccountsController ()
@property(strong) NSTextField *username;
@property(strong) NSTextField *home;
@property(strong) NSButton *hidden;
@property(strong) NSPopUpButton *operation;
@property(strong) NSTextView *commands;
@end

@implementation ServerAccountsController
- (instancetype)init
{
   self = [super initWithWindow:adminWindow(@"RStudio Server User Accounts", 620)];
   if (!self) return nil;
   NSView *view = self.window.contentView;
   label(view, @"Create a standard macOS account for RStudio with a private home. Hiding it from the login screen is optional. Run the generated commands in your own Terminal; macOS prompts for passwords there.", NSMakeRect(24, 545, 692, 55));
   label(view, @"Account name", NSMakeRect(24, 508, 125, 22));
   self.username = [[NSTextField alloc] initWithFrame:NSMakeRect(155, 505, 285, 26)];
   self.username.stringValue = @"rstudio_alice";
   self.username.delegate = self;
   [view addSubview:self.username];
   self.hidden = [NSButton checkboxWithTitle:@"Hide from login screen" target:self action:@selector(updateCommands:)];
   self.hidden.frame = NSMakeRect(460, 505, 255, 26);
   self.hidden.state = NSControlStateValueOn;
   [view addSubview:self.hidden];
   label(view, @"Home directory", NSMakeRect(24, 468, 125, 22));
   self.home = [[NSTextField alloc] initWithFrame:NSMakeRect(155, 465, 555, 26)];
   self.home.stringValue = @"/Users/RStudioHomes/rstudio_alice";
   self.home.delegate = self;
   [view addSubview:self.home];
   self.operation = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(20, 420, 295, 30) pullsDown:NO];
   [self.operation addItemsWithTitles:@[@"Create User", @"Change Visibility", @"Delete User", @"Uninstall Server"]];
   self.operation.target = self;
   self.operation.action = @selector(updateCommands:);
   [view addSubview:self.operation];
   label(view, @"Use a new home under an existing root-owned storage folder. For external storage, mount an ownership-enabled volume first. Accounts use /usr/bin/false and a 0700 home; login-screen hiding alone does not disable every macOS login mechanism.", NSMakeRect(24, 340, 692, 68));
   NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSMakeRect(24, 72, 692, 255)];
   scroll.hasVerticalScroller = YES;
   scroll.hasHorizontalScroller = YES;
   scroll.borderType = NSBezelBorder;
   self.commands = [[NSTextView alloc] initWithFrame:scroll.bounds];
   self.commands.editable = NO;
   self.commands.richText = NO;
   self.commands.font = [NSFont monospacedSystemFontOfSize:12 weight:NSFontWeightRegular];
   self.commands.autoresizingMask = NSViewWidthSizable;
   scroll.documentView = self.commands;
   [view addSubview:scroll];
   button(view, @"Copy Commands", NSMakeRect(490, 23, 225, 32), self, @selector(copyCommands:));
   label(view, @"Deletion preserves the home and refuses users with running processes.", NSMakeRect(24, 20, 450, 36));
   [self updateCommands:nil];
   return self;
}

- (void)controlTextDidChange:(NSNotification *)notification { [self updateCommands:nil]; }

- (void)updateCommands:(id)sender
{
   NSString *name = self.username.stringValue;
   NSRegularExpression *pattern = [NSRegularExpression regularExpressionWithPattern:@"^[a-z][a-z0-9_]{0,30}$" options:0 error:nil];
   NSString *home = self.home.stringValue;
   NSInteger operation = self.operation.indexOfSelectedItem;
   self.username.enabled = operation != 3;
   self.home.enabled = operation == 0;
   self.hidden.enabled = operation == 0 || operation == 1;
   if (operation == 3)
   {
      self.commands.string = [NSString stringWithFormat:
         @"# Quit all Server sessions first. Removes the app and installer-owned\n"
          "# system setup. User accounts/homes and modified config are preserved.\n"
          "sudo %@\n",
          shellQuote([NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"Contents/Resources/app/bin/uninstall-rstudio-server"])];
      return;
   }
   if ([name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound ||
       [pattern numberOfMatchesInString:name options:0 range:NSMakeRange(0, name.length)] != 1 || (operation == 0 && (
       !home.isAbsolutePath || [home rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound ||
       [home hasSuffix:@"/"] || [@[@".", @".."] containsObject:home.lastPathComponent])))
   {
      self.commands.string = @"Enter a lowercase account name beginning with a letter (maximum 31 characters) and an absolute path for a new home directory.";
      return;
   }
   NSString *admin = shellQuote(adminPath());
   NSString *user = shellQuote(name);
   NSString *parent = shellQuote(home.stringByDeletingLastPathComponent);
   NSString *visibility = self.hidden.state == NSControlStateValueOn ? @"--hidden" : @"--visible";
   if (operation == 1)
   {
      self.commands.string = [NSString stringWithFormat:@"sudo %@ set-user-visibility %@ %@\n",
         admin, user, self.hidden.state == NSControlStateValueOn ? @"hidden" : @"visible"];
      return;
   }
   if (operation == 2)
   {
      self.commands.string = [NSString stringWithFormat:
         @"# Quit this user's RStudio session before deleting its account.\n"
          "# The home is preserved and made root-owned/private.\n"
          "sudo %@ delete-user %@\n", admin, user];
      return;
   }
   self.commands.string = [NSString stringWithFormat:
      @"# Prepare the storage parent once, if it does not exist.\n"
       "# Mount external volumes first; do not create a missing mount point.\n"
       "if [ ! -e %@ ]; then sudo /bin/mkdir -m 755 %@; fi\n\n"
       "# Create the user; Terminal prompts securely for its password.\n"
       "sudo %@ create-user %@ --home %@ %@\n", parent, parent, admin, user, shellQuote(home), visibility];
}

- (void)copyCommands:(id)sender
{
   [NSPasteboard.generalPasteboard clearContents];
   [NSPasteboard.generalPasteboard setString:self.commands.string forType:NSPasteboardTypeString];
}
@end
