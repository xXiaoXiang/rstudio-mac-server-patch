/* Copyright (C) 2026 by Posit Software, PBC
 * Licensed under the GNU Affero General Public License, version 3. */
#import <Cocoa/Cocoa.h>

NSString *RStudioValidateNetwork(NSString *address, NSString *port);

@interface ServerSettingsController : NSWindowController
@end

@interface ServerAccountsController : NSWindowController <NSTextFieldDelegate>
@end
